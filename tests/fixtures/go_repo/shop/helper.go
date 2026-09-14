package shop

func ApplyDiscount(amount int) int {
	if amount > 100 {
		return amount - 10
	}
	return amount
}
