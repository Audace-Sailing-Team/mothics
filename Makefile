PACKAGE = mothics
VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
ALIAS_FILE = ~/.bashrc  # Change to ~/.zshrc if using Zsh

.PHONY: all venv install update pep8 clean install-service

# By default, create the virtual environment and install the package.
all: venv install

# Create a virtual environment if it doesn't exist.
venv:
	@test -d $(VENV) || python3 -m venv $(VENV)
	@echo "Virtual environment ready at $(VENV)"

# Install dependencies (if any) and your package into the virtual environment.
install: venv
	$(PIP) install --upgrade pip
	@if [ -f requirements.txt ]; then \
		$(PIP) install -r requirements.txt; \
	fi

# Update the package:
# - Pull the latest changes from git
# - Reinstall the package with any updates.
update: venv
	git pull

# Format your code and check for style issues.
pep8:
	autopep8 -r -i $(PACKAGE)
	flake8 $(PACKAGE)

# Clean up Python cache files and build artifacts.
clean:
	find . -type d -name '__pycache__' -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
	rm -rf build/ dist/ *.egg-info

# Install systemd service
install-service:
	@echo "Installing systemd service..."
	sudo cp mothics.service /etc/systemd/system/mothics@.service
	sudo systemctl daemon-reload
	sudo systemctl enable mothics@$(USER)
	sudo systemctl start mothics@$(USER)

# Add an alias for quickly attaching to the tmux session
alias-tmux:
	@if ! grep -q "alias mothics-join=" $(ALIAS_FILE); then \
		echo "alias mothics-join='tmux attach -t mothics'" >> $(ALIAS_FILE); \
		echo "Alias 'mothics-join' added to $(ALIAS_FILE)"; \
	fi
	@. $(ALIAS_FILE); echo "Alias 'mothics-join' is now available in this session."

