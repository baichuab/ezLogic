def double (n : Nat) : Nat := n + n

theorem double_eq (n : Nat) : double n = 2 * n := by
  unfold double
  omega

theorem double_add (a b : Nat) : double (a + b) = double a + double b := by
  rw [double_eq, double_eq, double_eq]
  ring_nf
  omega

theorem sum_le (a b c : Nat) (h1 : a ≤ b) (h2 : b ≤ c) : double a ≤ 2 * c := by
  have hac : a ≤ c := Nat.le_trans h1 h2
  rw [double_eq]
  obtain ⟨k, hk⟩ : ∃ k, c = a + k := ⟨c - a, by omega⟩
  subst hk
  omega

theorem add_zero' (n : Nat) : n + 0 = n := by
  induction n with
  | zero => rfl
  | succ m ih =>
    simp

theorem term_mode (a b : Nat) (h : a ≤ b) : double a ≤ double b :=
  Nat.add_le_add h h
