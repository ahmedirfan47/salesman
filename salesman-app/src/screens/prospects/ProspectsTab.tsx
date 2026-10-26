import { useCallback, useState } from "react";
import { View } from "react-native";
import { useBack } from "../../lib/use-back";
import { shared } from "../../components/ui";
import { ProspectListScreen } from "./ProspectListScreen";
import { ProspectDetailScreen } from "./ProspectDetailScreen";
import { NewProspectScreen } from "./NewProspectScreen";

type View_ = { name: "list" } | { name: "detail"; id: string } | { name: "new" };

/** Prospects tab: pipeline list -> prospect, list -> add a shop -> prospect. */
export function ProspectsTab() {
  const [view, setView] = useState<View_>({ name: "list" });
  const back = useCallback(() => setView({ name: "list" }), []);
  useBack(view.name !== "list", back);

  return (
    <View style={shared.screen}>
      {view.name === "list" && (
        <ProspectListScreen onOpen={(id) => setView({ name: "detail", id })} onNew={() => setView({ name: "new" })} />
      )}
      {view.name === "detail" && <ProspectDetailScreen id={view.id} onBack={back} />}
      {view.name === "new" && <NewProspectScreen onBack={back} onCreated={(id) => setView({ name: "detail", id })} />}
    </View>
  );
}