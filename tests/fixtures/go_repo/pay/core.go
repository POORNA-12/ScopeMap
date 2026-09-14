package pay

type Priced interface {
	GetPrice() int
}

type Processor struct {
	Name string
}

func (p *Processor) Run() int {
	return Calc(10)
}

func Calc(x int) int {
	return x + 1
}
