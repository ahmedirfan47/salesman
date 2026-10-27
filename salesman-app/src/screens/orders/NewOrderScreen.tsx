import { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  FlatList,
  Pressable,
  ScrollView,
  TextInput,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
} from "react-native";
import { Minus, Plus, Search, Store, UserPlus } from "lucide-react-native";
import { api, can } from "../../lib/api";
import { useAuth } from "../../lib/auth-context";
import { useBack } from "../../lib/use-back";
import { errorText, money } from "../../lib/format";
import type { AccountRow, AccountSettings, CatalogRow, Customer, Order } from "../../lib/types";
import {
  BackBar, Badge, Button, Card, Chip, Empty, ErrorText, Input, Loading, Notice, SectionTitle, shared,
} from "../../components/ui";
import { colors, radius, spacing, typography } from "../../theme/theme";

type Branch = { id: string; name: string; is_default: boolean; is_active: boolean };
type Step = "customer" | "items" | "review";
type Buyer =
  | { kind: "customer"; customer: Customer }
  | { kind: "walkin"; name: string; phone: string; branchId: string | null };

function priceOf(row: CatalogRow): number | null {
  return row.unit_price ?? row.price_min;
}

/** Why the server will hold this order for approval on credit grounds (mirrors its rules). */
function creditWarnings(acct: AccountRow | undefined, settings: AccountSettings | null, orderTotal: number): string[] {
  if (!acct || !settings) return [];
  const out: string[] = [];
  if (acct.on_hold) out.push("The customer's account is on hold.");
  if (settings.hold_when_overdue && Number(acct.blocking_overdue) > 0) {
    out.push(`${money(acct.overdue, acct.currency)} is overdue on this account.`);
  }
  if (settings.hold_over_limit && acct.credit_limit !== null) {
    const withVat = settings.prices_include_vat ? orderTotal : orderTotal * (1 + Number(settings.vat_rate) / 100);
    const after = Number(acct.exposure) + withVat;
    if (after > Number(acct.credit_limit)) {
      out.push(`This order takes the account to ${money(after, acct.currency)}, over its ${money(acct.credit_limit, acct.currency)} limit.`);
    }
  }
  return out;
}

/**
 * Take an order on the road: pick a customer (or a walk-in), add products
 * priced from that branch's price list with live stock, review, place.
 * Lines over stock still go through -- the server holds the order for a
 * manager's approval, exactly like a WhatsApp order.
 */
export function NewOrderScreen({ onBack, onCreated }: {
  onBack: () => void;
  /** the created order and a one-line message for the order screen */
  onCreated: (o: Order, notice: string) => void;
}) {
  const { me } = useAuth();
  const [step, setStep] = useState<Step>("customer");
  const [buyer, setBuyer] = useState<Buyer | null>(null);
  const [cart, setCart] = useState<Record<string, number>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [accounts, setAccounts] = useState<Record<string, AccountRow>>({});
  const [acctSettings, setAcctSettings] = useState<AccountSettings | null>(null);
  const seesAccounts = can(me, "view_accounts");

  // balances and credit terms, so the salesman knows before placing the order
  useEffect(() => {
    if (!seesAccounts) return;
    api("/accounts")
      .then((d: { customers: AccountRow[] }) => setAccounts(Object.fromEntries(d.customers.map((a) => [a.customer_id, a]))))
      .catch(() => setAccounts({}));
    api("/accounts/settings").then(setAcctSettings).catch(() => setAcctSettings(null));
  }, [seesAccounts]);

  const stepBack = useCallback(() => {
    setError("");
    if (step === "review") setStep("items");
    else if (step === "items") setStep("customer");
    else onBack();
  }, [step, onBack]);
  useBack(true, stepBack);

  const branchId = buyer?.kind === "customer" ? buyer.customer.branch_id : buyer?.branchId ?? null;

  // ---- catalog for the chosen branch ----
  const [catalog, setCatalog] = useState<CatalogRow[] | null>(null);
  useEffect(() => {
    if (!buyer) return;
    setCatalog(null);
    api("/products/catalog", {}, branchId)
      .then((rows: CatalogRow[]) => setCatalog(rows.filter((r) => r.is_active)))
      .catch((e) => {
        setError(errorText(e, "Failed to load products"));
        setCatalog([]);
      });
  }, [buyer, branchId]);

  const lines = useMemo(() => {
    if (!catalog) return [];
    return catalog
      .filter((r) => cart[r.sku] > 0)
      .map((r) => ({ row: r, qty: cart[r.sku], price: priceOf(r) ?? 0 }));
  }, [catalog, cart]);
  const units = lines.reduce((n, l) => n + l.qty, 0);
  const total = lines.reduce((n, l) => n + l.qty * l.price, 0);
  const currency = lines[0]?.row.currency ?? catalog?.find((r) => r.currency)?.currency ?? "";
  const short = lines.filter((l) => l.qty > l.row.stock);
  const account = buyer?.kind === "customer" ? accounts[buyer.customer.id] : undefined;
  const creditIssues = creditWarnings(account, acctSettings, total);

  function setQty(sku: string, qty: number) {
    setCart((c) => {
      const next = { ...c };
      if (qty > 0) next[sku] = Math.min(qty, 99999);
      else delete next[sku];
      return next;
    });
  }

  async function place() {
    if (!buyer || lines.length === 0) return;
    setBusy(true);
    setError("");
    const items = lines.map((l) => ({ sku: l.row.sku, quantity: l.qty }));
    const body =
      buyer.kind === "customer"
        ? { items, customer_id: buyer.customer.id }
        : {
            items,
            customer_name: buyer.name.trim(),
            whatsapp_number: buyer.phone.trim() || null,
            branch_id: buyer.branchId,
          };
    try {
      const order: Order = await api("/orders", { method: "POST", body: JSON.stringify(body) });
      let notice = `${order.order_number} is confirmed.`;
      if (order.status === "requires_human_review") {
        const why = [
          short.length > 0 ? "some items are short on stock" : null,
          creditIssues.length > 0 || short.length === 0 ? "the customer's account needs a check" : null,
        ].filter(Boolean).join(" and ");
        notice = `${order.order_number} is waiting for a manager's approval: ${why}.`;
      }
      onCreated(order, notice);
    } catch (e) {
      setError(errorText(e, "Failed to place the order"));
      setBusy(false);
    }
  }

  const title = step === "customer" ? "New order" : buyerName(buyer);

  return (
    <KeyboardAvoidingView style={shared.screen} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <BackBar title={title} onBack={stepBack} />
      {step === "customer" && (
        <CustomerStep
          accounts={accounts}
          defaultBranch={me?.branch_id ?? null}
          onPick={(b) => {
            if (!buyer || buyerKey(buyer) !== buyerKey(b) || branchOf(buyer) !== branchOf(b)) setCart({});
            setBuyer(b);
            setStep("items");
          }}
        />
      )}

      {step === "items" && (
        <>
          {catalog === null ? (
            <Loading />
          ) : (
            <ItemsStep catalog={catalog} cart={cart} setQty={setQty} error={error} />
          )}
          <View style={styles.footer}>
            <View style={styles.flex}>
              <Text style={styles.footerTotal}>{money(total, currency)}</Text>
              <Text style={shared.dim}>{units} unit{units === 1 ? "" : "s"} · {lines.length} product{lines.length === 1 ? "" : "s"}</Text>
            </View>
            <Button label="Review" onPress={() => setStep("review")} disabled={lines.length === 0} />
          </View>
        </>
      )}

      {step === "review" && (
        <>
          <ScrollView contentContainerStyle={shared.list}>
            <ErrorText text={error} />
            {short.length > 0 && (
              <Notice
                tone="warning"
                text="Some items are short on stock. The order will wait for a manager's approval before it's confirmed."
              />
            )}
            {creditIssues.length > 0 && (
              <Notice tone="danger" text={`${creditIssues.join(" ")} The order will wait for a manager's approval.`} />
            )}
            <SectionTitle style={styles.firstTitle}>CUSTOMER</SectionTitle>
            <Card>
              <Text style={shared.title}>{buyerName(buyer)}</Text>
              {buyer?.kind === "customer" && buyer.customer.company && buyer.customer.company !== buyer.customer.name ? (
                <Text style={shared.meta}>{buyer.customer.company}</Text>
              ) : null}
              {buyerPhone(buyer) ? <Text style={shared.meta}>{buyerPhone(buyer)}</Text> : null}
              {account ? <AccountLine account={account} /> : null}
            </Card>
            <SectionTitle>ITEMS</SectionTitle>
            <Card>
              {lines.map((l, idx) => (
                <View key={l.row.sku} style={[styles.line, idx > 0 && styles.lineBorder]}>
                  <View style={styles.flex}>
                    <Text style={styles.product}>{l.row.name_en}</Text>
                    <Text style={shared.dim}>{l.qty} × {money(l.price)}</Text>
                    {l.qty > l.row.stock && (
                      <Text style={styles.shortText}>Only {l.row.stock} in stock</Text>
                    )}
                  </View>
                  <Text style={styles.amount}>{money(l.qty * l.price)}</Text>
                </View>
              ))}
              <View style={[styles.line, styles.lineBorder]}>
                <Text style={styles.totalLabel}>Total</Text>
                <Text style={styles.footerTotal}>{money(total, currency)}</Text>
              </View>
            </Card>
            <Text style={[shared.dim, styles.fine]}>
              Prices come from today's price list and are checked again when the order is placed.
            </Text>
          </ScrollView>
          <View style={styles.footer}>
            <Button label="Edit items" variant="outline" onPress={() => setStep("items")} disabled={busy} />
            <Button label="Place order" onPress={place} busy={busy} style={styles.flex} />
          </View>
        </>
      )}
    </KeyboardAvoidingView>
  );
}

function buyerName(b: Buyer | null): string {
  if (!b) return "New order";
  return b.kind === "customer" ? b.customer.name : b.name.trim() || "Walk-in customer";
}
function buyerPhone(b: Buyer | null): string | null {
  if (!b) return null;
  return b.kind === "customer" ? b.customer.whatsapp_number : b.phone.trim() || null;
}
function buyerKey(b: Buyer): string {
  return b.kind === "customer" ? b.customer.id : "walkin";
}
function branchOf(b: Buyer): string | null {
  return b.kind === "customer" ? b.customer.branch_id : b.branchId;
}

// ---------------------------------------------------------------- customer
function AccountLine({ account }: { account: AccountRow }) {
  const owes = Number(account.balance);
  const parts = [owes > 0 ? `Owes ${money(account.balance, account.currency)}` : "Nothing owed"];
  const available = account.available_credit === null ? null : Number(account.available_credit);
  if (available !== null && available >= 0) parts.push(`${money(available, account.currency)} credit left`);
  const flags = [
    account.on_hold ? "On hold" : null,
    Number(account.overdue) > 0 ? "Overdue" : null,
    available !== null && available < 0 ? `${money(-available, account.currency)} over limit` : null,
  ].filter(Boolean) as string[];
  return (
    <View style={[shared.inline, styles.accountLine]}>
      <Text style={shared.dim}>{parts.join(" · ")}</Text>
      {flags.map((f) => <Badge key={f} label={f} tone="danger" />)}
    </View>
  );
}

function CustomerStep({ accounts, defaultBranch, onPick }: {
  accounts: Record<string, AccountRow>; defaultBranch: string | null; onPick: (b: Buyer) => void;
}) {
  const [customers, setCustomers] = useState<Customer[] | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [walkIn, setWalkIn] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [branchId, setBranchId] = useState<string | null>(defaultBranch);

  useEffect(() => {
    api("/customers")
      .then((rows: Customer[]) => setCustomers(rows.filter((c) => c.is_active)))
      .catch((e) => {
        setError(errorText(e, "Failed to load customers"));
        setCustomers([]);
      });
    api("/branches")
      .then((rows: Branch[]) => {
        const active = rows.filter((b) => b.is_active);
        setBranches(active);
        setBranchId((cur) => cur ?? active.find((b) => b.is_default)?.id ?? active[0]?.id ?? null);
      })
      .catch(() => setBranches([]));
  }, []);

  const rows = useMemo(() => {
    const term = q.trim().toLowerCase();
    const list = customers ?? [];
    if (!term) return list;
    return list.filter((c) =>
      [c.name, c.company, c.whatsapp_number, c.address].some((v) => v?.toLowerCase().includes(term)),
    );
  }, [customers, q]);

  if (customers === null) return <Loading />;

  return (
    <FlatList
      contentContainerStyle={shared.list}
      data={walkIn ? [] : rows}
      keyExtractor={(c) => c.id}
      keyboardShouldPersistTaps="handled"
      ListHeaderComponent={
        <>
          <ErrorText text={error} />
          {walkIn ? (
            <Card>
              <Text style={[shared.title, styles.cardTitle]}>Walk-in or new customer</Text>
              <Input value={name} onChangeText={setName} placeholder="Customer or shop name" />
              <Input
                value={phone}
                onChangeText={setPhone}
                placeholder="WhatsApp number (optional)"
                keyboardType="phone-pad"
                style={styles.gap}
              />
              {branches.length > 1 && (
                <>
                  <Text style={[shared.dim, styles.gap]}>Branch</Text>
                  <View style={[shared.inline, styles.chipsWrap]}>
                    {branches.map((b) => (
                      <Chip key={b.id} label={b.name} active={branchId === b.id} onPress={() => setBranchId(b.id)} />
                    ))}
                  </View>
                </>
              )}
              <View style={[shared.inline, styles.gapLg]}>
                <Button label="Cancel" variant="outline" small onPress={() => setWalkIn(false)} />
                <Button
                  label="Continue"
                  small
                  disabled={!name.trim()}
                  onPress={() => onPick({ kind: "walkin", name, phone, branchId })}
                />
              </View>
            </Card>
          ) : (
            <>
              <View style={styles.search}>
                <Search size={16} color={colors.textDim} />
                <Input
                  value={q}
                  onChangeText={setQ}
                  placeholder="Search customers"
                  style={styles.searchInput}
                  autoCorrect={false}
                />
              </View>
              <Pressable onPress={() => setWalkIn(true)} accessibilityRole="button">
                <Card style={styles.walkIn}>
                  <UserPlus size={18} color={colors.accent} />
                  <Text style={styles.walkInText}>Walk-in or new customer</Text>
                </Card>
              </Pressable>
              <SectionTitle>CUSTOMERS ({rows.length})</SectionTitle>
            </>
          )}
        </>
      }
      ListEmptyComponent={walkIn ? null : <Empty text={customers.length ? "No customers match." : "No customers yet."} />}
      renderItem={({ item }) => (
        <Pressable onPress={() => onPick({ kind: "customer", customer: item })} accessibilityRole="button">
          {({ pressed }) => (
            <Card style={[styles.customerRow, pressed && styles.pressed]}>
              <Store size={18} color={colors.textDim} />
              <View style={styles.flex}>
                <Text style={shared.title} numberOfLines={1}>{item.name}</Text>
                <Text style={shared.meta} numberOfLines={1}>
                  {[item.company !== item.name ? item.company : null, item.whatsapp_number, item.address].filter(Boolean).join(" · ") ||
                    "No details"}
                </Text>
                {accounts[item.id] ? <AccountLine account={accounts[item.id]} /> : null}
              </View>
            </Card>
          )}
        </Pressable>
      )}
    />
  );
}

// ---------------------------------------------------------------- items
function ItemsStep({
  catalog,
  cart,
  setQty,
  error,
}: {
  catalog: CatalogRow[];
  cart: Record<string, number>;
  setQty: (sku: string, qty: number) => void;
  error: string;
}) {
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return catalog;
    return catalog.filter((r) =>
      [r.name_en, r.name_ar, r.sku, r.category].some((v) => v?.toLowerCase().includes(term)),
    );
  }, [catalog, q]);

  return (
    <FlatList
      contentContainerStyle={shared.list}
      data={rows}
      keyExtractor={(r) => r.id}
      keyboardShouldPersistTaps="handled"
      ListHeaderComponent={
        <>
          <ErrorText text={error} />
          <View style={[styles.search, styles.searchGap]}>
            <Search size={16} color={colors.textDim} />
            <Input
              value={q}
              onChangeText={setQ}
              placeholder="Search products or SKU"
              style={styles.searchInput}
              autoCorrect={false}
            />
          </View>
        </>
      }
      ListEmptyComponent={<Empty text={catalog.length ? "No products match." : "No active products."} />}
      renderItem={({ item }) => {
        const price = priceOf(item);
        const qty = cart[item.sku] ?? 0;
        const ranged = item.unit_price === null && item.price_min !== null && item.price_min !== item.price_max;
        return (
          <Card style={qty > 0 ? styles.inCart : undefined}>
            <View style={shared.between}>
              <View style={styles.flex}>
                <Text style={shared.title} numberOfLines={2}>{item.name_en}</Text>
                <Text style={shared.dim}>{item.sku}{item.category ? ` · ${item.category}` : ""}</Text>
              </View>
              <Text style={styles.price}>
                {price === null
                  ? "No price"
                  : ranged
                    ? `${money(item.price_min)}–${money(item.price_max)}`
                    : money(price, item.currency)}
              </Text>
            </View>
            <View style={[shared.between, styles.itemFooter]}>
              {item.stock > 0 ? (
                <Badge label={`${item.stock} in stock`} tone={qty > item.stock ? "warning" : "success"} />
              ) : (
                <Badge label="Out of stock" tone="danger" />
              )}
              {price === null ? (
                <Text style={shared.dim}>Not on this branch's price list</Text>
              ) : (
                <Stepper value={qty} onChange={(n) => setQty(item.sku, n)} />
              )}
            </View>
          </Card>
        );
      }}
    />
  );
}

function Stepper({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  if (value === 0) {
    return <Button label="Add" icon={Plus} small variant="outline" onPress={() => onChange(1)} />;
  }
  return (
    <View style={styles.stepper}>
      <Pressable style={styles.stepBtn} onPress={() => onChange(value - 1)} hitSlop={6} accessibilityLabel="Less">
        <Minus size={16} color={colors.accent} />
      </Pressable>
      <TextInput
        value={String(value)}
        onChangeText={(t) => onChange(parseInt(t.replace(/\D/g, "") || "0", 10))}
        keyboardType="number-pad"
        style={styles.stepInput}
        selectTextOnFocus
        accessibilityLabel="Quantity"
      />
      <Pressable style={styles.stepBtn} onPress={() => onChange(value + 1)} hitSlop={6} accessibilityLabel="More">
        <Plus size={16} color={colors.accent} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  firstTitle: { marginTop: 0 },
  cardTitle: { marginBottom: spacing.sm + 4 },
  gap: { marginTop: spacing.sm },
  gapLg: { marginTop: spacing.md },
  chipsWrap: { marginTop: spacing.xs },
  search: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.pill,
    paddingLeft: spacing.md,
    backgroundColor: colors.surface,
    marginBottom: spacing.sm,
  },
  searchGap: { marginBottom: spacing.md },
  searchInput: { flex: 1, minWidth: 0, borderWidth: 0, backgroundColor: "transparent", paddingVertical: 9, paddingLeft: 0 },
  walkIn: { flexDirection: "row", alignItems: "center", gap: spacing.sm, borderStyle: "dashed", borderColor: colors.accent },
  walkInText: { ...typography.bodyMedium, color: colors.accent },
  customerRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm + 4 },
  pressed: { backgroundColor: colors.surface },
  inCart: { borderColor: colors.accent },
  price: { fontSize: 14, fontWeight: "700", color: colors.text },
  itemFooter: { marginTop: spacing.sm + 2 },
  stepper: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.pill,
  },
  stepBtn: { paddingHorizontal: 12, paddingVertical: 8 },
  stepInput: { width: 52, textAlign: "center", fontSize: 15, fontWeight: "600", color: colors.text, paddingVertical: 6 },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm + 4,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 4,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.white,
  },
  footerTotal: { fontSize: 17, fontWeight: "700", color: colors.text },
  line: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.sm + 2 },
  lineBorder: { borderTopWidth: 1, borderTopColor: colors.border },
  product: { ...typography.caption, color: colors.text, fontWeight: "600" },
  shortText: { ...typography.caption, color: colors.warning, marginTop: 2 },
  amount: { ...typography.caption, color: colors.text, fontWeight: "500" },
  totalLabel: { ...typography.bodyMedium, color: colors.text, flex: 1 },
  fine: { marginTop: spacing.sm, textAlign: "center" },
  accountLine: { marginTop: 4 },
});