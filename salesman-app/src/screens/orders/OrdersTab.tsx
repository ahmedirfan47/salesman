import { useCallback, useState } from "react";
import { View } from "react-native";
import { useBack } from "../../lib/use-back";
import { shared } from "../../components/ui";
import { OrderListScreen } from "./OrderListScreen";
import { OrderDetailScreen } from "./OrderDetailScreen";
import { NewOrderScreen } from "./NewOrderScreen";

type View_ =
  | { name: "list" }
  | { name: "detail"; id: string; notice?: string }
  | { name: "new" };

/** Orders tab: list -> detail, list -> new order -> detail. */
export function OrdersTab({ canCreate }: { canCreate: boolean }) {
  const [view, setView] = useState<View_>({ name: "list" });
  const back = useCallback(() => setView({ name: "list" }), []);
  // NewOrderScreen handles back itself (it steps back through its own pages).
  useBack(view.name === "detail", back);

  return (
    <View style={shared.screen}>
      {view.name === "list" && (
        <OrderListScreen
          onOpen={(id) => setView({ name: "detail", id })}
          onNew={canCreate ? () => setView({ name: "new" }) : undefined}
        />
      )}
      {view.name === "detail" && <OrderDetailScreen id={view.id} notice={view.notice} onBack={back} />}
      {view.name === "new" && (
        <NewOrderScreen
          onBack={back}
          onCreated={(order, notice) => setView({ name: "detail", id: order.id, notice })}
        />
      )}
    </View>
  );
}