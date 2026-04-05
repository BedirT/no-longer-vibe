package models

import "time"

// Exported constants
const MaxRetries = 3
const defaultTimeout = 5

// Exported variable
var Version = "1.0.0"
var internal = "hidden"

// Exported type
type User struct {
	ID   int
	Name string
}

// Unexported type
type cache struct {
	data map[string]string
}

// Exported interface
type Repository interface {
	FindByID(id int) (*User, error)
	Save(user *User) error
}

// Exported function
func NewUser(name string) *User {
	return &User{Name: name}
}

// Unexported function
func validate(u *User) bool {
	return u.Name != ""
}

// Method on exported type
func (u *User) FullName() string {
	return u.Name
}

// Method on unexported type
func (c *cache) get(key string) string {
	return c.data[key]
}

// init function
func init() {
	_ = time.Now()
}
