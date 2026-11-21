import Mathlib

def double (n : ℕ) : ℕ := 2 * n

theorem double_eq (n : ℕ) : double n = n + n := by
  unfold double
  ring

theorem double_mono {a b : ℕ} (h : a ≤ b) : double a ≤ double b := by
  rw [double_eq, double_eq]
  exact Nat.add_le_add h h

example : double 2 = 4 := double_eq 2 ▸ rfl

example (a : ℕ) : a ≤ double a := by
  rw [double_eq]
  exact Nat.le_add_right a a

theorem and_left (p q : Prop) (h : p ∧ q) : p := h.1
