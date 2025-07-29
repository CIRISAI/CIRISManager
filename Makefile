# Makefile for CIRISManager
# Standard development commands

.PHONY: help install dev test test-cov lint format clean run-api run docs

help:  ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

install:  ## Install production dependencies
	pip install -r requirements.txt

dev:  ## Install development dependencies
	pip install -e ".[dev]"
	@echo "Development environment ready! Run 'make test' to verify."

test:  ## Run tests
	pytest tests/ -v

test-cov:  ## Run tests with coverage report
	pytest tests/ -v --cov=ciris_manager --cov-report=term-missing --cov-report=html
	@echo "Coverage report generated in htmlcov/"

lint:  ## Run linters (ruff, mypy)
	ruff check ciris_manager/ tests/
	mypy ciris_manager/

format:  ## Format code with ruff
	ruff format ciris_manager/ tests/
	ruff check --fix ciris_manager/ tests/

clean:  ## Clean up generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .coverage htmlcov/ .pytest_cache/ .ruff_cache/ .mypy_cache/
	rm -rf test-env/ build/ dist/ *.egg-info/

run-api:  ## Run the API server (development mode)
	@if [ -z "$$CIRIS_MANAGER_CONFIG" ] && [ ! -f "config.yml" ]; then \
		echo "❌ No config found! Run: export CIRIS_MANAGER_CONFIG=\$$(pwd)/config.yml"; \
		echo "   Or run ./quickstart.sh to set up local development"; \
		exit 1; \
	fi
	@if [ -z "$$CIRIS_MANAGER_CONFIG" ]; then \
		export CIRIS_MANAGER_CONFIG=$$(pwd)/config.yml; \
	fi
	CIRIS_MANAGER_CONFIG=$${CIRIS_MANAGER_CONFIG:-$$(pwd)/config.yml} python deployment/run-ciris-manager-api.py

run:  ## Run the full manager service
	ciris-manager --config config.example.yml

docs:  ## Build documentation (when available)
	@echo "Documentation building not yet configured"