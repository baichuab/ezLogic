mutual
  def isEven : ℕ → Prop
    | 0 => True
    | n + 1 => isOdd n
  def isOdd : ℕ → Prop
    | 0 => False
    | n + 1 => isEven n
end

mutual
  theorem even_or_odd_even : ∀ n, isEven n ∨ isOdd n
    | 0 => Or.inl trivial
    | n + 1 => (even_or_odd_odd n).symm
  theorem even_or_odd_odd : ∀ n, isEven n ∨ isOdd n
    | 0 => Or.inl trivial
    | n + 1 => (even_or_odd_even n).symm
end
