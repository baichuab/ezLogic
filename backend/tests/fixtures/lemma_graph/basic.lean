import Mathlib

theorem double_sum (n : ℕ) : 2 * (Finset.range (n+1)).sum id = n * (n + 1) := by
  induction n with
  | zero => simp
  | succ k ih => rw [Finset.sum_range_succ, mul_add, ih]; simp [id]; ring

lemma uses_local (n : ℕ) : n * (n + 1) = 2 * (Finset.range (n+1)).sum id := (double_sum n).symm

theorem broken (a : ℕ) : a + 1 > a := by
  rw [Nat.add_comm]
  exact nonexistent_lemma a

example (a b : ℕ) : a + b = b + a := by rw [Nat.add_comm]

private theorem priv_thm (p q : Prop) (hp : p) (hq : q) : p ∧ q := ⟨hp, hq⟩
