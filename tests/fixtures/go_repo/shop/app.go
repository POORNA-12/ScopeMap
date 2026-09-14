package shop

import (
	"fmt"

	"example.com/shop/pay"
)

func Checkout() int {
	fmt.Println("processing checkout")
	total := pay.Calc(20)
	return ApplyDiscount(total)
}
