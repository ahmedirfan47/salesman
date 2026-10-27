"""UBL 2.1 e-invoices for ZATCA: build, hash, sign (XAdES) and stamp the QR code.

The order of operations matters and mirrors ZATCA's SDK:

1. Build the unsigned invoice (it already holds the ICV, the previous invoice
   hash and a placeholder for the QR code).
2. Hash it: drop UBLExtensions, cac:Signature and the QR reference,
   canonicalise (C14N) and SHA-256.
3. Sign the hash, digest the signed properties, and insert the UBLExtensions
   block right after the opening <Invoice> tag.
4. Build the QR code (which contains the hash and the signature) and put it in
   the placeholder.

Steps 3 and 4 only touch the parts the hash leaves out, so the signed
document hashes to the same value; sign() checks that before returning.
The XML is assembled as text, never re-serialised, because ZATCA's validator
hashes the signed properties exactly as they are indented here.
"""
import base64
import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from xml.sax.saxutils import escape

from lxml import etree

from app.modules.zatca import crypto

# base64(hex(sha256("0"))): the "previous invoice hash" of an EGS unit's first document
FIRST_PIH = "NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjNzljMmRiYzIzOWRkNGU5MWI0NjcyOWQ3M2EyN2ZiNTdlOQ=="
QR_PLACEHOLDER = "SET_QR_CODE_DATA"

NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
}

TYPE_CODES = {"invoice": "388", "credit_note": "381", "debit_note": "383"}
# KSA-2 transaction code: position 1-2 = 01 standard (B2B) / 02 simplified (B2C)
SUBTYPES = {"standard": "0100000", "simplified": "0200000"}

CENT = Decimal("0.01")


def _m(value) -> str:
    return str(Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP))


def _qty(value) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _price(net: Decimal, qty: Decimal) -> str:
    """Unit net price precise enough that quantity x price reproduces the line amount."""
    p = (net / qty).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    text = format(p.normalize(), "f")
    if "." not in text:
        return text + ".00"
    whole, frac = text.split(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def _pct(value) -> str:
    return _m(value)


def _x(value) -> str:
    return escape(str(value or "").strip())


# ---- the document -----------------------------------------------------------------------------

@dataclass
class Address:
    street: str
    building_number: str
    district: str
    city: str
    postal_code: str
    country: str = "SA"
    additional_street: str | None = None


@dataclass
class Party:
    name: str
    address: Address | None = None
    vat_number: str | None = None
    other_id: str | None = None          # e.g. the commercial registration number
    other_id_scheme: str = "CRN"


@dataclass
class Line:
    name: str
    quantity: Decimal
    net: Decimal          # line amount excluding VAT
    vat: Decimal
    vat_rate: Decimal
    unit_code: str = "PCE"


@dataclass
class Document:
    number: str
    uuid: str
    kind: str              # invoice | credit_note | debit_note
    flow: str              # standard | simplified
    issue_date: date
    issue_time: str        # HH:MM:SS, Saudi local time
    icv: int
    pih: str
    seller: Party
    buyer: Party | None
    lines: list[Line]
    currency: str = "SAR"
    supply_date: date | None = None
    payment_means_code: str = "10"
    billing_reference: str | None = None   # credit/debit notes: the invoice number corrected
    reason: str | None = None              # credit/debit notes: why
    totals: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        net = sum((Decimal(str(ln.net)) for ln in self.lines), Decimal("0"))
        vat = sum((Decimal(str(ln.vat)) for ln in self.lines), Decimal("0"))
        self.totals = {"net": net, "vat": vat, "gross": net + vat}

    @property
    def type_code(self) -> str:
        return TYPE_CODES[self.kind]


def validate(doc: Document) -> list[str]:
    """What ZATCA would reject, in plain words, before anything is signed."""
    problems: list[str] = []
    s = doc.seller
    if not s.vat_number or len(s.vat_number) != 15 or not s.vat_number.isdigit() \
            or s.vat_number[0] != "3" or s.vat_number[-1] != "3":
        problems.append("The business VAT number must be 15 digits, starting and ending with 3.")
    if not s.other_id:
        problems.append("The business commercial registration (CR) number is missing.")
    a = s.address
    if a is None or not all([a.street, a.building_number, a.district, a.city, a.postal_code]):
        problems.append("The business address needs street, building number, district, city and postal code.")
    else:
        if not (len(a.building_number) == 4 and a.building_number.isdigit()):
            problems.append("The business building number must be 4 digits.")
        if not (len(a.postal_code) == 5 and a.postal_code.isdigit()):
            problems.append("The business postal code must be 5 digits.")
    if doc.flow == "standard":
        b = doc.buyer
        if b is None:
            problems.append("A standard (B2B) invoice needs the customer's details.")
        else:
            if b.vat_number and (len(b.vat_number) != 15 or not b.vat_number.isdigit()
                                 or b.vat_number[0] != "3" or b.vat_number[-1] != "3"):
                problems.append("The customer's VAT number must be 15 digits, starting and ending with 3.")
            if not b.vat_number and not b.other_id:
                problems.append("The customer needs a VAT number or a commercial registration number.")
            ba = b.address
            if ba is None or not all([ba.street, ba.building_number, ba.district, ba.city, ba.postal_code]):
                problems.append("The customer's address needs street, building number, district, city and postal code.")
            elif ba.country == "SA" and not (len(ba.postal_code) == 5 and ba.postal_code.isdigit()):
                problems.append("The customer's postal code must be 5 digits.")
    if doc.kind in ("credit_note", "debit_note"):
        if not doc.billing_reference:
            problems.append("A credit or debit note must name the invoice it corrects.")
        if not (doc.reason or "").strip():
            problems.append("A credit or debit note needs a reason.")
    if not doc.lines:
        problems.append("The document has no lines.")
    for ln in doc.lines:
        if Decimal(str(ln.quantity)) <= 0 or Decimal(str(ln.net)) < 0:
            problems.append(f"Line '{ln.name}' must have a positive quantity and amount.")
        if Decimal(str(ln.vat_rate)) <= 0:
            problems.append(f"Line '{ln.name}' has no VAT; zero-rated and exempt items aren't supported yet.")
    return problems


def _address_xml(a: Address, pad: str) -> str:
    rows = [f"{pad}<cac:PostalAddress>", f"{pad}    <cbc:StreetName>{_x(a.street)}</cbc:StreetName>"]
    if a.additional_street:
        rows.append(f"{pad}    <cbc:AdditionalStreetName>{_x(a.additional_street)}</cbc:AdditionalStreetName>")
    rows += [
        f"{pad}    <cbc:BuildingNumber>{_x(a.building_number)}</cbc:BuildingNumber>",
        f"{pad}    <cbc:CitySubdivisionName>{_x(a.district)}</cbc:CitySubdivisionName>",
        f"{pad}    <cbc:CityName>{_x(a.city)}</cbc:CityName>",
        f"{pad}    <cbc:PostalZone>{_x(a.postal_code)}</cbc:PostalZone>",
        f"{pad}    <cac:Country>",
        f"{pad}        <cbc:IdentificationCode>{_x(a.country or 'SA')}</cbc:IdentificationCode>",
        f"{pad}    </cac:Country>",
        f"{pad}</cac:PostalAddress>",
    ]
    return "\n".join(rows)


def _party_xml(p: Party | None, role: str) -> str:
    tag = f"cac:Accounting{role}Party"
    if p is None:
        return f"    <{tag}/>"
    rows = [f"    <{tag}>", "        <cac:Party>"]
    if p.other_id and not (role == "Customer" and p.vat_number):
        rows += [
            "            <cac:PartyIdentification>",
            f'                <cbc:ID schemeID="{_x(p.other_id_scheme)}">{_x(p.other_id)}</cbc:ID>',
            "            </cac:PartyIdentification>",
        ]
    if p.address is not None:
        rows.append(_address_xml(p.address, " " * 12))
    if p.vat_number:
        rows += [
            "            <cac:PartyTaxScheme>",
            f"                <cbc:CompanyID>{_x(p.vat_number)}</cbc:CompanyID>",
            "                <cac:TaxScheme>",
            "                    <cbc:ID>VAT</cbc:ID>",
            "                </cac:TaxScheme>",
            "            </cac:PartyTaxScheme>",
        ]
    elif role == "Customer":
        rows += [
            "            <cac:PartyTaxScheme>",
            "                <cac:TaxScheme>",
            "                    <cbc:ID>VAT</cbc:ID>",
            "                </cac:TaxScheme>",
            "            </cac:PartyTaxScheme>",
        ]
    rows += [
        "            <cac:PartyLegalEntity>",
        f"                <cbc:RegistrationName>{_x(p.name)}</cbc:RegistrationName>",
        "            </cac:PartyLegalEntity>",
        "        </cac:Party>",
        f"    </{tag}>",
    ]
    return "\n".join(rows)


def build_unsigned(doc: Document) -> str:
    """The invoice as text, with a QR placeholder and no UBLExtensions yet."""
    ccy = _x(doc.currency)
    by_rate: dict[Decimal, list[Decimal]] = {}
    for ln in doc.lines:
        bucket = by_rate.setdefault(Decimal(str(ln.vat_rate)), [Decimal("0"), Decimal("0")])
        bucket[0] += Decimal(str(ln.net))
        bucket[1] += Decimal(str(ln.vat))
    t = doc.totals

    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<Invoice xmlns="{NS["inv"]}" xmlns:cac="{NS["cac"]}" xmlns:cbc="{NS["cbc"]}" xmlns:ext="{NS["ext"]}">',
        "    <cbc:ProfileID>reporting:1.0</cbc:ProfileID>",
        f"    <cbc:ID>{_x(doc.number)}</cbc:ID>",
        f"    <cbc:UUID>{_x(doc.uuid)}</cbc:UUID>",
        f"    <cbc:IssueDate>{doc.issue_date.isoformat()}</cbc:IssueDate>",
        f"    <cbc:IssueTime>{doc.issue_time}</cbc:IssueTime>",
        f'    <cbc:InvoiceTypeCode name="{SUBTYPES[doc.flow]}">{doc.type_code}</cbc:InvoiceTypeCode>',
        f"    <cbc:DocumentCurrencyCode>{ccy}</cbc:DocumentCurrencyCode>",
        "    <cbc:TaxCurrencyCode>SAR</cbc:TaxCurrencyCode>",
    ]
    if doc.billing_reference:
        rows += [
            "    <cac:BillingReference>",
            "        <cac:InvoiceDocumentReference>",
            f"            <cbc:ID>{_x(doc.billing_reference)}</cbc:ID>",
            "        </cac:InvoiceDocumentReference>",
            "    </cac:BillingReference>",
        ]
    rows += [
        "    <cac:AdditionalDocumentReference>",
        "        <cbc:ID>ICV</cbc:ID>",
        f"        <cbc:UUID>{doc.icv}</cbc:UUID>",
        "    </cac:AdditionalDocumentReference>",
        "    <cac:AdditionalDocumentReference>",
        "        <cbc:ID>PIH</cbc:ID>",
        "        <cac:Attachment>",
        f'            <cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">{doc.pih}</cbc:EmbeddedDocumentBinaryObject>',
        "        </cac:Attachment>",
        "    </cac:AdditionalDocumentReference>",
        "    <cac:AdditionalDocumentReference>",
        "        <cbc:ID>QR</cbc:ID>",
        "        <cac:Attachment>",
        f'            <cbc:EmbeddedDocumentBinaryObject mimeCode="text/plain">{QR_PLACEHOLDER}</cbc:EmbeddedDocumentBinaryObject>',
        "        </cac:Attachment>",
        "    </cac:AdditionalDocumentReference>",
        "    <cac:Signature>",
        "        <cbc:ID>urn:oasis:names:specification:ubl:signature:Invoice</cbc:ID>",
        "        <cbc:SignatureMethod>urn:oasis:names:specification:ubl:dsig:enveloped:xades</cbc:SignatureMethod>",
        "    </cac:Signature>",
        _party_xml(doc.seller, "Supplier"),
        _party_xml(doc.buyer, "Customer"),
    ]
    if doc.supply_date:
        rows += [
            "    <cac:Delivery>",
            f"        <cbc:ActualDeliveryDate>{doc.supply_date.isoformat()}</cbc:ActualDeliveryDate>",
            "    </cac:Delivery>",
        ]
    rows += ["    <cac:PaymentMeans>", f"        <cbc:PaymentMeansCode>{_x(doc.payment_means_code)}</cbc:PaymentMeansCode>"]
    if doc.kind in ("credit_note", "debit_note"):
        rows.append(f"        <cbc:InstructionNote>{_x(doc.reason)[:1000]}</cbc:InstructionNote>")
    rows.append("    </cac:PaymentMeans>")
    rows += [
        "    <cac:TaxTotal>",
        f'        <cbc:TaxAmount currencyID="SAR">{_m(t["vat"])}</cbc:TaxAmount>',
        "    </cac:TaxTotal>",
        "    <cac:TaxTotal>",
        f'        <cbc:TaxAmount currencyID="{ccy}">{_m(t["vat"])}</cbc:TaxAmount>',
    ]
    for rate, (taxable, tax) in sorted(by_rate.items()):
        rows += [
            "        <cac:TaxSubtotal>",
            f'            <cbc:TaxableAmount currencyID="{ccy}">{_m(taxable)}</cbc:TaxableAmount>',
            f'            <cbc:TaxAmount currencyID="{ccy}">{_m(tax)}</cbc:TaxAmount>',
            "            <cac:TaxCategory>",
            '                <cbc:ID schemeID="UN/ECE 5305" schemeAgencyID="6">S</cbc:ID>',
            f"                <cbc:Percent>{_pct(rate)}</cbc:Percent>",
            "                <cac:TaxScheme>",
            '                    <cbc:ID schemeID="UN/ECE 5153" schemeAgencyID="6">VAT</cbc:ID>',
            "                </cac:TaxScheme>",
            "            </cac:TaxCategory>",
            "        </cac:TaxSubtotal>",
        ]
    rows += [
        "    </cac:TaxTotal>",
        "    <cac:LegalMonetaryTotal>",
        f'        <cbc:LineExtensionAmount currencyID="{ccy}">{_m(t["net"])}</cbc:LineExtensionAmount>',
        f'        <cbc:TaxExclusiveAmount currencyID="{ccy}">{_m(t["net"])}</cbc:TaxExclusiveAmount>',
        f'        <cbc:TaxInclusiveAmount currencyID="{ccy}">{_m(t["gross"])}</cbc:TaxInclusiveAmount>',
        f'        <cbc:AllowanceTotalAmount currencyID="{ccy}">0.00</cbc:AllowanceTotalAmount>',
        f'        <cbc:PrepaidAmount currencyID="{ccy}">0.00</cbc:PrepaidAmount>',
        f'        <cbc:PayableAmount currencyID="{ccy}">{_m(t["gross"])}</cbc:PayableAmount>',
        "    </cac:LegalMonetaryTotal>",
    ]
    for i, ln in enumerate(doc.lines, start=1):
        qty, net, vat = Decimal(str(ln.quantity)), Decimal(str(ln.net)), Decimal(str(ln.vat))
        rows += [
            "    <cac:InvoiceLine>",
            f"        <cbc:ID>{i}</cbc:ID>",
            f'        <cbc:InvoicedQuantity unitCode="{_x(ln.unit_code)}">{_qty(qty)}</cbc:InvoicedQuantity>',
            f'        <cbc:LineExtensionAmount currencyID="{ccy}">{_m(net)}</cbc:LineExtensionAmount>',
            "        <cac:TaxTotal>",
            f'            <cbc:TaxAmount currencyID="{ccy}">{_m(vat)}</cbc:TaxAmount>',
            f'            <cbc:RoundingAmount currencyID="{ccy}">{_m(net + vat)}</cbc:RoundingAmount>',
            "        </cac:TaxTotal>",
            "        <cac:Item>",
            f"            <cbc:Name>{_x(ln.name)}</cbc:Name>",
            "            <cac:ClassifiedTaxCategory>",
            "                <cbc:ID>S</cbc:ID>",
            f"                <cbc:Percent>{_pct(ln.vat_rate)}</cbc:Percent>",
            "                <cac:TaxScheme>",
            "                    <cbc:ID>VAT</cbc:ID>",
            "                </cac:TaxScheme>",
            "            </cac:ClassifiedTaxCategory>",
            "        </cac:Item>",
            "        <cac:Price>",
            f'            <cbc:PriceAmount currencyID="{ccy}">{_price(net, qty)}</cbc:PriceAmount>',
            "        </cac:Price>",
            "    </cac:InvoiceLine>",
        ]
    rows.append("</Invoice>")
    return "\n".join(rows)


# ---- hashing ----------------------------------------------------------------------------------

def _remove_keeping_whitespace(el) -> None:
    """Remove an element but keep the text that followed it, as a DOM removal would."""
    parent = el.getparent()
    tail = el.tail or ""
    prev = el.getprevious()
    if prev is not None:
        prev.tail = (prev.tail or "") + tail
    else:
        parent.text = (parent.text or "") + tail
    parent.remove(el)


def invoice_hash(xml: str | bytes) -> str:
    """base64 SHA-256 of the canonical invoice without its signature and QR code."""
    data = xml.encode() if isinstance(xml, str) else xml
    root = etree.fromstring(data, parser=etree.XMLParser(remove_blank_text=False, resolve_entities=False))
    for path in (
        "ext:UBLExtensions",
        "cac:Signature",
        "cac:AdditionalDocumentReference[cbc:ID='QR']",
    ):
        for el in root.xpath(path, namespaces=NS):
            _remove_keeping_whitespace(el)
    canonical = etree.tostring(root, method="c14n", exclusive=False, with_comments=False)
    return base64.b64encode(hashlib.sha256(canonical).digest()).decode()


# ---- signing ----------------------------------------------------------------------------------

def _signed_properties(signing_time: str, cert: crypto.CertInfo, *, for_hashing: bool) -> str:
    """xades:SignedProperties. ZATCA digests the form with namespace declarations on each element."""
    xades_ns = ' xmlns:xades="http://uri.etsi.org/01903/v1.3.2#"' if for_hashing else ""
    ds_ns = ' xmlns:ds="http://www.w3.org/2000/09/xmldsig#"' if for_hashing else ""
    pad = " " * 32
    return (
        f'<xades:SignedProperties{xades_ns} Id="xadesSignedProperties">\n'
        f"{pad}    <xades:SignedSignatureProperties>\n"
        f"{pad}        <xades:SigningTime>{signing_time}</xades:SigningTime>\n"
        f"{pad}        <xades:SigningCertificate>\n"
        f"{pad}            <xades:Cert>\n"
        f"{pad}                <xades:CertDigest>\n"
        f'{pad}                    <ds:DigestMethod{ds_ns} Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>\n'
        f"{pad}                    <ds:DigestValue{ds_ns}>{cert.digest}</ds:DigestValue>\n"
        f"{pad}                </xades:CertDigest>\n"
        f"{pad}                <xades:IssuerSerial>\n"
        f"{pad}                    <ds:X509IssuerName{ds_ns}>{escape(cert.issuer)}</ds:X509IssuerName>\n"
        f"{pad}                    <ds:X509SerialNumber{ds_ns}>{cert.serial_number}</ds:X509SerialNumber>\n"
        f"{pad}                </xades:IssuerSerial>\n"
        f"{pad}            </xades:Cert>\n"
        f"{pad}        </xades:SigningCertificate>\n"
        f"{pad}    </xades:SignedSignatureProperties>\n"
        f"{pad}</xades:SignedProperties>"
    )


def signed_properties_digest(signing_time: str, cert: crypto.CertInfo) -> str:
    return crypto.hex_digest_b64(_signed_properties(signing_time, cert, for_hashing=True))


def _ubl_extensions(inv_hash: str, signature: str, cert: crypto.CertInfo, signing_time: str) -> str:
    props_digest = signed_properties_digest(signing_time, cert)
    return f"""<ext:UBLExtensions>
    <ext:UBLExtension>
        <ext:ExtensionURI>urn:oasis:names:specification:ubl:dsig:enveloped:xades</ext:ExtensionURI>
        <ext:ExtensionContent>
            <sig:UBLDocumentSignatures xmlns:sig="urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2" xmlns:sac="urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2" xmlns:sbc="urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2">
                <sac:SignatureInformation>
                    <cbc:ID>urn:oasis:names:specification:ubl:signature:1</cbc:ID>
                    <sbc:ReferencedSignatureID>urn:oasis:names:specification:ubl:signature:Invoice</sbc:ReferencedSignatureID>
                    <ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="signature">
                        <ds:SignedInfo>
                            <ds:CanonicalizationMethod Algorithm="http://www.w3.org/2006/12/xml-c14n11"/>
                            <ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"/>
                            <ds:Reference Id="invoiceSignedData" URI="">
                                <ds:Transforms>
                                    <ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116">
                                        <ds:XPath>not(//ancestor-or-self::ext:UBLExtensions)</ds:XPath>
                                    </ds:Transform>
                                    <ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116">
                                        <ds:XPath>not(//ancestor-or-self::cac:Signature)</ds:XPath>
                                    </ds:Transform>
                                    <ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116">
                                        <ds:XPath>not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID='QR'])</ds:XPath>
                                    </ds:Transform>
                                    <ds:Transform Algorithm="http://www.w3.org/2006/12/xml-c14n11"/>
                                </ds:Transforms>
                                <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
                                <ds:DigestValue>{inv_hash}</ds:DigestValue>
                            </ds:Reference>
                            <ds:Reference Type="http://www.w3.org/2000/09/xmldsig#SignatureProperties" URI="#xadesSignedProperties">
                                <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>
                                <ds:DigestValue>{props_digest}</ds:DigestValue>
                            </ds:Reference>
                        </ds:SignedInfo>
                        <ds:SignatureValue>{signature}</ds:SignatureValue>
                        <ds:KeyInfo>
                            <ds:X509Data>
                                <ds:X509Certificate>{cert.base64_body}</ds:X509Certificate>
                            </ds:X509Data>
                        </ds:KeyInfo>
                        <ds:Object>
                            <xades:QualifyingProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" Target="signature">
                                {_signed_properties(signing_time, cert, for_hashing=False)}
                            </xades:QualifyingProperties>
                        </ds:Object>
                    </ds:Signature>
                </sac:SignatureInformation>
            </sig:UBLDocumentSignatures>
        </ext:ExtensionContent>
    </ext:UBLExtension>
</ext:UBLExtensions>"""


# ---- QR code ----------------------------------------------------------------------------------

def _tlv(tag: int, value: bytes) -> bytes:
    if len(value) > 255:
        raise ValueError(f"QR field {tag} is too long")
    return bytes([tag, len(value)]) + value


def _clip_utf8(text: str, limit: int = 127) -> bytes:
    """Cut on a character boundary so Arabic never breaks mid-letter."""
    data = text.encode()
    if len(data) <= limit:
        return data
    return data[:limit].decode("utf-8", errors="ignore").encode()


def qr_payload(*, seller_name: str, vat_number: str, timestamp: str, total: str, vat_total: str,
               inv_hash: str, signature: str, public_key_der: bytes, cert_signature: bytes | None) -> str:
    """ZATCA's TLV QR content, base64. Tag 9 (the certificate's signature) is for simplified invoices."""
    data = b"".join([
        _tlv(1, _clip_utf8(seller_name)),
        _tlv(2, vat_number.encode()),
        _tlv(3, timestamp.encode()),
        _tlv(4, total.encode()),
        _tlv(5, vat_total.encode()),
        _tlv(6, inv_hash.encode()),
        _tlv(7, signature.encode()),
        _tlv(8, public_key_der),
    ] + ([_tlv(9, cert_signature)] if cert_signature else []))
    return base64.b64encode(data).decode()


def decode_qr(payload: str) -> dict[int, bytes]:
    data, out, i = base64.b64decode(payload), {}, 0
    while i < len(data):
        tag, length = data[i], data[i + 1]
        out[tag] = data[i + 2:i + 2 + length]
        i += 2 + length
    return out


@dataclass
class Signed:
    xml: str
    invoice_hash: str
    signature: str
    qr: str
    signing_time: str


def sign(doc: Document, cert_base64: str, private_key_pem: str, *, signing_time: datetime | None = None) -> Signed:
    """Build, hash, sign and stamp a document. Raises ValueError if it can't be done correctly."""
    unsigned = build_unsigned(doc)
    inv_hash = invoice_hash(unsigned)
    cert = crypto.certificate_info(cert_base64)
    signature = crypto.sign_hash(inv_hash, private_key_pem)
    when = (signing_time or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    open_tag_end = unsigned.index(">", unsigned.index("<Invoice")) + 1
    signed = unsigned[:open_tag_end] + _ubl_extensions(inv_hash, signature, cert, when) + unsigned[open_tag_end:]
    qr = qr_payload(
        seller_name=doc.seller.name, vat_number=doc.seller.vat_number or "",
        timestamp=f"{doc.issue_date.isoformat()}T{doc.issue_time}",
        total=_m(doc.totals["gross"]), vat_total=_m(doc.totals["vat"]),
        inv_hash=inv_hash, signature=signature, public_key_der=cert.public_key_der,
        cert_signature=cert.signature if doc.flow == "simplified" else None,
    )
    signed = signed.replace(QR_PLACEHOLDER, qr, 1)

    if invoice_hash(signed) != inv_hash:
        raise ValueError("Signing changed the invoice content")
    if not crypto.verify_hash_signature(inv_hash, signature, crypto.load_private_key(private_key_pem).public_key()):
        raise ValueError("The signature does not verify")
    return Signed(xml=signed, invoice_hash=inv_hash, signature=signature, qr=qr, signing_time=when)


def qr_from_xml(xml: str | bytes) -> str | None:
    """The QR payload in a (possibly ZATCA-cleared) invoice."""
    data = xml.encode() if isinstance(xml, str) else xml
    root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False))
    found = root.xpath(
        "cac:AdditionalDocumentReference[cbc:ID='QR']/cac:Attachment/cbc:EmbeddedDocumentBinaryObject/text()",
        namespaces=NS,
    )
    return str(found[0]).strip() if found else None