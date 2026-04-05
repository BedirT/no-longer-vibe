package service

type Service struct {
	db Database
}

type Database interface {
	Query(q string) ([]byte, error)
}

func NewService(db Database) *Service {
	return &Service{db: db}
}

func (s *Service) Run() error {
	data, err := s.db.Query("SELECT 1")
	if err != nil {
		return err
	}
	return s.process(data)
}

func (s *Service) process(data []byte) error {
	return nil
}

func (s Service) String() string {
	return "service"
}
