package service_test

import (
	"testing"

	"github.com/example/myproject/service"
)

func TestNewService(t *testing.T) {
	svc := service.NewService(nil)
	if svc == nil {
		t.Fatal("expected non-nil service")
	}
}

func TestServiceRun(t *testing.T) {
	t.Skip("not implemented")
}
