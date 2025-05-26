# Cross-Country Planner Makefile
# Usage: make <target>

# Build all containers
build:
	docker compose build

# Start all services in the background
down:
	docker compose down

up run:
	docker compose up -d

# Show logs for all services
logs:
	docker compose logs -f

restart: down clean build up

# Run backend tests inside the backend container
test-backend:
	docker compose exec backend pytest test_main.py

# Run frontend tests inside the frontend container
test-frontend:
	docker compose exec frontend npm test -- --watchAll=false

# Run all tests
test: test-backend test-frontend

# Remove all containers, images, and volumes (full cleanup)
clean:
	docker compose down -v --rmi all --remove-orphans
	rm -rf backend/__pycache__

# Clean and rebuild everything
rebuild: clean build

# Update airports and airspace data (can be run manually or by cron)
update-data:
	docker compose exec backend python update_data.py

.PHONY: build up run down logs test-backend test-frontend test clean rebuild update-data 
