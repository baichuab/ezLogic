def helper (n : Nat) : Nat := n + 1

theorem helper_pos (n : Nat) : 0 < helper n := by
  unfold helper
  omega

mutual
  def isEven : Nat → Bool
    | 0 => true
    | n + 1 => isOdd n
  def isOdd : Nat → Bool
    | 0 => false
    | n + 1 => isEven n
end

theorem isEven_zero : isEven 0 = true := by
  rfl

theorem uses_both : isOdd 1 = true ∧ 0 < helper 0 := by
  constructor
  · rfl
  · exact helper_pos 0
