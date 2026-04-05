package server

import (
	"fmt"
	"net/http"
	"os"

	"github.com/example/myproject/internal/config"
	"github.com/gorilla/mux"
)

func StartServer() {
	cfg := config.Load()
	r := mux.NewRouter()
	fmt.Println("Starting on", cfg.Port)
	http.ListenAndServe(":"+os.Getenv("PORT"), r)
}
