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

# Install systemd services
install-service:
	@echo "Installing systemd service..."
	sudo cp mothics.service /etc/systemd/system/mothics@.service
	sudo systemctl daemon-reload
	sudo systemctl enable mothics@$(USER)
	sudo systemctl start mothics@$(USER)

install-vpn:
	@echo "Installing systemd VPN service..."
	sudo cp vpn.service /etc/systemd/system/openfortivpn@.service
	sudo systemctl daemon-reload
	sudo systemctl enable openfortivpn@$(USER)
	sudo systemctl start openfortivpn@$(USER)

install-modem:
	@echo "Installing systemd modem service..."
	sudo cp modem.service /etc/systemd/system/wvdial@.service
	sudo systemctl daemon-reload
	sudo systemctl enable wvdial@$(USER)
	sudo systemctl start wvdial@$(USER)

# Add an alias for quickly attaching to the tmux session
alias-tmux:
	@if ! grep -q "alias mothics-join=" $(ALIAS_FILE); then \
		echo "alias mothics-join='tmux attach -t mothics'" >> $(ALIAS_FILE); \
		source $(ALIAS_FILE);\
		echo "Alias 'mothics-join' added to $(ALIAS_FILE)"; \
	fi
	@. $(ALIAS_FILE); echo "Alias 'mothics-join' is now available in this session."

# Add an alias to start the Mothics CLI
alias-start:
	@if ! grep -q "alias mothics-start=" $(ALIAS_FILE); then \
		echo "alias mothics-start='. $(VENV)/bin/activate && python3 cli.py'" >> $(ALIAS_FILE); \
		echo "Alias 'mothics-start' added to $(ALIAS_FILE)"; \
	fi
	@. $(ALIAS_FILE); echo "Alias 'mothics-start' is now available in this session."
