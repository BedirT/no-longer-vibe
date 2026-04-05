package contracts

// Reader is the basic reading interface.
type Reader interface {
	Read(p []byte) (n int, err error)
}

// Writer is the basic writing interface.
type Writer interface {
	Write(p []byte) (n int, err error)
}

// ReadWriter combines Reader and Writer.
type ReadWriter interface {
	Reader
	Writer
}

// Closer adds a Close method.
type Closer interface {
	Close() error
}

// TypeAlias for function type
type HandlerFunc func(w Writer, r Reader)

// Exported constant block
const (
	StatusOK    = 200
	StatusError = 500
)

// Var block with mixed visibility
var (
	DefaultReader Reader
	internalState int
)
