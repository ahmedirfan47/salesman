"""ZATCA cryptography: keys, the CSR, certificates and the invoice signature.

Everything here follows ZATCA's "Electronic Invoice Security Features
Implementation Standards" and was checked against the signed samples and test
certificate shipped with ZATCA's own Java SDK (see tests/test_zatca.py):

- Keys are ECDSA on secp256k1 (ZATCA rejects P-256).
- The CSR carries the environment's certificate template name and a
  directory name with the EGS serial, VAT number, invoice types, location and
  industry.
- The certificate digest is base64 of the *hex* SHA-256 of the certificate's
  base64 text -- a ZATCA quirk, not a mistake.
- The invoice signature is ECDSA-SHA256 over the 32 raw bytes of the invoice
  hash, DER encoded, then base64.
"""
import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ObjectIdentifier

TEMPLATE_NAMES = {
    "sandbox": "TSTZATCA-Code-Signing",
    "simulation": "PREZATCA-Code-Signing",
    "production": "ZATCA-Code-Signing",
}
_TEMPLATE_OID = ObjectIdentifier("1.3.6.1.4.1.311.20.2")
_REGISTERED_ADDRESS = ObjectIdentifier("2.5.4.26")
_BUSINESS_CATEGORY = ObjectIdentifier("2.5.4.15")

# RDN labels as ZATCA prints the issuer name (X509IssuerName)
_DN_LABELS = {
    "2.5.4.3": "CN", "2.5.4.4": "SN", "2.5.4.5": "SERIALNUMBER", "2.5.4.6": "C", "2.5.4.7": "L",
    "2.5.4.8": "ST", "2.5.4.10": "O", "2.5.4.11": "OU", "2.5.4.12": "T",
    "0.9.2342.19200300.100.1.1": "UID", "0.9.2342.19200300.100.1.25": "DC", "1.2.840.113549.1.9.1": "E",
}


# ---- keys -------------------------------------------------------------------------------------

def new_private_key_pem() -> str:
    key = ec.generate_private_key(ec.SECP256K1())
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()


def load_private_key(pem: str) -> ec.EllipticCurvePrivateKey:
    text = pem.strip()
    if "-----BEGIN" not in text:  # a bare base64 body
        text = f"-----BEGIN EC PRIVATE KEY-----\n{text}\n-----END EC PRIVATE KEY-----"
    key = serialization.load_pem_private_key(text.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256k1":
        raise ValueError("ZATCA needs an EC private key on the secp256k1 curve")
    return key


# ---- CSR --------------------------------------------------------------------------------------

@dataclass
class CsrInput:
    common_name: str          # e.g. "EGS1-886431145" -- free text chosen by the taxpayer
    organization: str         # taxpayer name
    organization_unit: str    # branch name (or the 10-digit TIN for VAT groups)
    vat_number: str           # 15 digits, starts and ends with 3
    egs_serial: str           # "1-<solution>|2-<model>|3-<serial>"
    invoice_types: str        # "1100" standard + simplified, "1000" standard only, "0100" simplified only
    location: str             # branch address
    industry: str             # business category, e.g. "Wholesale"
    country: str = "SA"


def build_csr(data: CsrInput, private_key_pem: str, environment: str) -> str:
    """A PEM certificate signing request in the shape ZATCA's CSID endpoints accept."""
    key = load_private_key(private_key_pem)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, data.country),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, data.organization_unit),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, data.organization),
        x509.NameAttribute(NameOID.COMMON_NAME, data.common_name),
    ])
    directory = x509.Name([
        x509.NameAttribute(NameOID.SURNAME, data.egs_serial),
        x509.NameAttribute(NameOID.USER_ID, data.vat_number),
        x509.NameAttribute(NameOID.TITLE, data.invoice_types),
        x509.NameAttribute(_REGISTERED_ADDRESS, data.location),
        x509.NameAttribute(_BUSINESS_CATEGORY, data.industry),
    ])
    template = TEMPLATE_NAMES[environment].encode()
    template_der = bytes([0x0C, len(template)]) + template  # UTF8String
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(subject)
        .add_extension(x509.UnrecognizedExtension(_TEMPLATE_OID, template_der), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DirectoryName(directory)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM).decode()


def csr_for_api(csr_pem: str) -> str:
    """The CSID endpoints take the whole PEM text, base64 encoded."""
    return base64.b64encode(csr_pem.encode()).decode()


# ---- certificates -----------------------------------------------------------------------------

@dataclass
class CertInfo:
    base64_body: str      # the certificate as one base64 line (what goes in ds:X509Certificate)
    digest: str           # xades CertDigest value
    issuer: str           # X509IssuerName, e.g. "CN=PRZEINVOICESCA4-CA, DC=extgazt, DC=gov, DC=local"
    serial_number: str    # decimal
    public_key_der: bytes  # SubjectPublicKeyInfo (QR tag 8)
    signature: bytes       # the certificate's own signature (QR tag 9)
    not_after: datetime
    public_key: ec.EllipticCurvePublicKey


def certificate_from_token(binary_security_token: str) -> str:
    """CSID responses wrap the certificate's base64 text in another layer of base64."""
    return base64.b64decode(binary_security_token).decode().strip()


def _format_name(name: x509.Name) -> str:
    parts = []
    for rdn in name.rdns:
        attr = next(iter(rdn))
        parts.append(f"{_DN_LABELS.get(attr.oid.dotted_string, attr.oid.dotted_string)}={attr.value}")
    return ", ".join(reversed(parts))


def certificate_info(cert_base64: str) -> CertInfo:
    body = "".join(
        line.strip() for line in cert_base64.strip().splitlines() if line.strip() and not line.startswith("-----")
    )
    der = base64.b64decode(body)
    cert = x509.load_der_x509_certificate(der)
    hex_digest = hashlib.sha256(body.encode()).hexdigest()
    public_key = cert.public_key()
    return CertInfo(
        base64_body=body,
        digest=base64.b64encode(hex_digest.encode()).decode(),
        issuer=_format_name(cert.issuer),
        serial_number=str(cert.serial_number),
        public_key_der=public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        signature=cert.signature,
        not_after=cert.not_valid_after_utc,
        public_key=public_key,
    )


def key_matches_certificate(private_key_pem: str, cert: CertInfo) -> bool:
    mine = load_private_key(private_key_pem).public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return mine == cert.public_key_der


# ---- signing ----------------------------------------------------------------------------------

def sign_hash(invoice_hash_b64: str, private_key_pem: str) -> str:
    digest = base64.b64decode(invoice_hash_b64)
    if len(digest) != 32:
        raise ValueError("The invoice hash must be a base64 SHA-256 digest")
    signature = load_private_key(private_key_pem).sign(digest, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(signature).decode()


def verify_hash_signature(invoice_hash_b64: str, signature_b64: str, public_key: ec.EllipticCurvePublicKey) -> bool:
    try:
        public_key.verify(base64.b64decode(signature_b64), base64.b64decode(invoice_hash_b64), ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:  # noqa: BLE001
        return False


def hex_digest_b64(text: str) -> str:
    """base64(hex(sha256(text))) -- how ZATCA encodes the SignedProperties digest."""
    return base64.b64encode(hashlib.sha256(text.encode()).hexdigest().encode()).decode()


def demo_certificate(private_key_pem: str, common_name: str) -> str:
    """A self-signed certificate for the demo account only -- ZATCA would never accept it."""
    key = load_private_key(private_key_pem)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    issuer = x509.Name([
        x509.NameAttribute(NameOID.DOMAIN_COMPONENT, "local"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Salesman Demo CA (not ZATCA)"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(issuer).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365 * 3)).sign(key, hashes.SHA256())
    )
    return base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()