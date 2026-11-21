-- Executed in the exact environment returned by the final source check.
-- No model-provided dependency lists are consumed.
run_cmd do
  let env := (← Lean.getEnv).setExporting false
  let namedTheorem := fun name =>
    match env.find? name with
    | some (.thmInfo _) => !(Lean.privateToUserName name).isInternalDetail
    | _ => false
  let rec proofBody (expr : Lean.Expr) : Lean.Expr :=
    match expr with
    | .lam _ _ body _ | .mdata _ body => proofBody body
    | _ => expr
  let candidates := env.constants.toList.filterMap fun (name, info) =>
    match info with
    | .thmInfo _ =>
      if (env.getModuleIdxFor? name).isNone && namedTheorem name then some name else none
    | _ => none
  let preferred := candidates.filter fun n =>
    let label := (Lean.privateToUserName n).toString
    label == "ezlogic_main" || label.endsWith ".ezlogic_main"
  let roots := if preferred.isEmpty then candidates else preferred
  unless roots.length == 1 do
    throwError "Graph needs one named theorem, or exactly one theorem named ezlogic_main."
  let root := roots.head!
  let axioms ← Lean.collectAxioms root
  for ax in axioms do
    unless ["propext", "Classical.choice", "Quot.sound"].contains ax.toString do
      throwError "Graph unavailable: root depends on unapproved axiom {ax}."
  let mut pending : Array (Lean.Name × Nat) := #[(root, 0)]
  let mut seen : Lean.NameSet := ({} : Lean.NameSet).insert root
  let mut rows : Array Lean.Json := #[]
  let mut cursor := 0
  while cursor < pending.size do
    let (name, depth) := pending[cursor]!
    cursor := cursor + 1
    let some info := env.find? name | throwError "Missing graph declaration {name}."
    let deps := info.getUsedConstantsAsSet.toList
    let isTheorem := namedTheorem name
    -- Lean gives `theorem` and `lemma` the same ConstantInfo kind. The outer
    -- lambda annotations repeat the statement's parameter types.
    let proofDeps := match info with
      | .thmInfo thm => (proofBody thm.value).getUsedConstantsAsSet.toList.filter fun n => n != name && namedTheorem n
      | _ => []
    let extra := deps.filter fun n => !seen.contains n
    let expand := depth < 2 && pending.size + extra.length ≤ 512
    unless expand || depth > 0 do
      throwError "Root has too many dependencies for the graph limit."
    if expand then
      for dep in extra do
        seen := seen.insert dep
        pending := pending.push (dep, depth + 1)
    let statement ← Lean.Elab.Command.liftTermElabM do
      return (← Lean.Meta.ppExpr info.type).pretty
    rows := rows.push <| Lean.Json.mkObj [
      ("node_id", Lean.toJson name.toString),
      ("lean_name", Lean.toJson (Lean.privateToUserName name).toString),
      ("statement", Lean.toJson statement),
      ("kind", Lean.toJson (if isTheorem then "theorem" else "technical")),
      ("proof_dependency_ids", if expand && isTheorem then Lean.toJson (proofDeps.map Lean.Name.toString) else Lean.Json.null),
      ("depends_on_ids", if expand then Lean.toJson (deps.map Lean.Name.toString) else Lean.Json.null)]
  let result := Lean.Json.mkObj [
    ("root_node_id", Lean.toJson root.toString),
    ("nodes", Lean.Json.arr rows)]
  Lean.logInfo m!"EZLOGIC_GRAPH_JSON:{result.compress}"
