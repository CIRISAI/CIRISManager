# Makefile for CIRISManager
# Standard development commands

.PHONY: help install dev test test-cov lint format clean run docs

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

run:  ## Run the full manager service
	ciris-manager --config config.example.yml

docs:  ## Build documentation (when available)
	@echo "Documentation building not yet configured"
