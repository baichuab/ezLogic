theorem and_swap (p q : Prop) : p ∧ q → q ∧ p := by
  intro h
  rcases h with ⟨hp, hq⟩
  constructor
  · exact hq
  · exact hp

theorem sum_formula (n : Nat) : 2 * (List.range (n + 1)).sum = n * (n + 1) := by
  induction n with
  | zero => rfl
  | succ k ih =>
    rw [List.range_succ, List.sum_append, Nat.mul_add, ih]
    simp
    ring_nf

theorem or_comm' (p q : Prop) (h : p ∨ q) : q ∨ p := by
  cases h with
  | inl hp => exact Or.inr hp
  | inr hq =>
    have hq' : q := hq
    exact Or.inl hq'

theorem uses_swap (a b : Prop) (ha : a) (hb : b) : b ∧ a :=
  and_swap a b ⟨ha, hb⟩

example : 2 + 2 = 4 := by decide
