theorem s (p q : Prop) (hp : p) : p ∧ q := by
  constructor
  · exact hp
  · sorry

theorem done (p : Prop) (hp : p) : p := by
  exact hp
