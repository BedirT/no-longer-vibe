package handlers

import (
	"fmt"
	mylog "log"
	. "strings"
	_ "net/http/pprof"
)

func Handle() {
	mylog.Println("handling")
	fmt.Println(ToUpper("test"))
}
