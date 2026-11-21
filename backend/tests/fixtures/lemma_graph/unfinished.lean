theorem fine (a b : ℕ) : a + b = b + a := Nat.add_comm a b

example (n : ℕ) : n + 0 = n := by
  rw [Nat.add_zero]

/- an unclosed comment swallows everything after it
