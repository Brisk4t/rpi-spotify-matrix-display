PYTHON_CMD ?= python3
IS_RPI := $(shell grep -qi "Raspberry Pi" /proc/device-tree/model 2>/dev/null && echo 1)
BOOT_DIR := $(shell [ -d /boot/firmware ] && echo /boot/firmware || echo /boot)

# Pinned to the last commit with the classic setup.py Python binding. Newer commits
# require Python 3.11+ and Pillow 12, which do not run on older Pis (e.g. Pi Zero / Bullseye).
RGBMATRIX_REPO := https://github.com/hzeller/rpi-rgb-led-matrix.git
RGBMATRIX_COMMIT := d8778b5f044b216acef2dec723bc9bdcd227cd8d

install: ## Install dependencies and request Spotify credentials
	@if ! command -v $(PYTHON_CMD) >/dev/null 2>&1 || ! $(PYTHON_CMD) -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then \
		echo "❌ Python 3.9 or newer is required. Use \033[1;36mmake PYTHON_CMD=/path/to/python3\033[0m to select an interpreter."; \
		exit 1; \
	fi
	@if command -v apt-get >/dev/null 2>&1; then \
		PYTHON_VER=$$($(PYTHON_CMD) -c 'import sys; print("%d.%d" % sys.version_info[:2])'); \
		PKGS="python$$PYTHON_VER-venv python$$PYTHON_VER-dev"; \
		if [ -n "$(IS_RPI)" ]; then PKGS="$$PKGS git build-essential liblcms2-2 libopenjp2-7 libwebpdemux2 libwebpmux3"; fi; \
		echo "📦 Ensuring $$PKGS are installed..."; \
		sudo apt-get update >/dev/null 2>&1 || true; \
		sudo DEBIAN_FRONTEND=noninteractive apt-get install -y $$PKGS >/dev/null 2>&1 || echo "⚠️  Could not install some of: $$PKGS"; \
	fi
	$(PYTHON_CMD) -m venv .venv
	.venv/bin/pip install --upgrade pip setuptools wheel
	@# --prefer-binary avoids compiling packages from source when an older prebuilt wheel exists (e.g. piwheels)
	@if [ -n "$(IS_RPI)" ]; then \
		.venv/bin/pip install --prefer-binary -e . "Pillow<12" && $(MAKE) --no-print-directory rpi-rgbmatrix; \
	else \
		.venv/bin/pip install --prefer-binary -e ".[emulator]"; \
	fi
	@rm -rf *.egg-info/
	@if [ ! -f config.ini ]; then cp config.ini.example config.ini; fi
	@if grep -q "client_id = <YOUR_CLIENT_ID_HERE>" config.ini; then \
		echo ""; \
		echo "Please provide your Spotify API credentials:"; \
		echo "You can obtain these from: https://developer.spotify.com/dashboard"; \
		echo ""; \
		read -p "Enter Spotify Client ID: " client_id; \
		read -p "Enter Spotify Client Secret: " client_secret; \
		echo ""; \
		echo "Optional: Provide your sp_dc cookie to fetch lyrics."; \
		echo "You can find it by following these instructions: https://github.com/akashrchandran/syrics/wiki/Finding-sp_dc"; \
		echo "Leave blank to skip for now."; \
		read -p "Enter sp_dc cookie (optional): " sp_dc; \
		sed "s/client_id = <YOUR_CLIENT_ID_HERE>/client_id = $$client_id/" config.ini > config.ini.tmp && mv config.ini.tmp config.ini; \
		sed "s/client_secret = <YOUR_CLIENT_SECRET_HERE>/client_secret = $$client_secret/" config.ini > config.ini.tmp && mv config.ini.tmp config.ini; \
		if [ -n "$$sp_dc" ]; then \
			sed "s|sp_dc = <YOUR SP_DC COOKIE FOR LYRICS>|sp_dc = $$sp_dc|" config.ini > config.ini.tmp && mv config.ini.tmp config.ini; \
			sed "s/^lyrics = false/lyrics = true/" config.ini > config.ini.tmp && mv config.ini.tmp config.ini; \
		fi; \
	fi
	@echo ""
	@echo "✅ rpi-spotify-matrix-display successfully installed!"
	@echo ""
	@echo "🧮 To run on an pi-connected matrix: \033[1;36mmake run\033[0m"
	@echo "🖥️ To run within an emulator window: \033[1;36mmake emulate\033[0m"

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

clean: ## Reset repo to a clean state
	@echo "🧹 Resetting repo to a clean state...";
	rm -rf build/ dist/ *.egg-info/ .venv/ rpi-rgb-led-matrix/
	rm -f .cache config.ini matrix.log
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || sudo rm -rf {} +
	find . -type f -name "*.pyc" -exec rm -f {} + 2>/dev/null || sudo rm -f {} +
	@if [ -f /etc/systemd/system/matrix.service ]; then \
		echo "🗑 Removing matrix systemd service..."; \
		sudo systemctl stop matrix || true; \
		sudo systemctl disable matrix || true; \
		sudo rm /etc/systemd/system/matrix.service; \
		sudo systemctl daemon-reload; \
	fi
	@if grep -q "alias matrix=" ~/.bash_aliases 2>/dev/null; then \
		echo "🗑 Removed 'matrix' alias from ~/.bash_aliases"; \
		sed "/alias matrix=/d" ~/.bash_aliases > ~/.bash_aliases.tmp && mv ~/.bash_aliases.tmp ~/.bash_aliases; \
	fi
	@echo "✅ Repo cleaned."

check-venv:
	@if [ ! -d .venv ]; then \
		echo "❌ Error: Virtual environment not found. Please run 'make' first."; \
		exit 1; \
	fi

emulate: check-venv ## Run the display within an emulator window
	.venv/bin/python main.py --emulate

## RASPBERRY PI SPECIFIC TARGETS ##

run: check-venv rpi-rgbmatrix rpi-optimize rpi-service ## Run the display on a raspberry pi connected matrix
	@echo "▶️ Starting Spotify Matrix Display..."
	sudo .venv/bin/python main.py

check-rpi:
	@if [ ! -f /proc/device-tree/model ] || ! grep -qi "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then \
		echo "❌ Error: This command can only be run on a Raspberry Pi."; \
		exit 1; \
	fi

rpi-rgbmatrix: check-venv check-rpi ## Raspberry Pi ONLY - Build and install the rgbmatrix library
	@if .venv/bin/python -c 'import rgbmatrix' >/dev/null 2>&1; then \
		echo "✅ rgbmatrix is already installed."; \
	else \
		echo "📦 Building rgbmatrix (this can take a while on older Pis)..."; \
		rm -rf rpi-rgb-led-matrix && mkdir rpi-rgb-led-matrix && \
		git -C rpi-rgb-led-matrix init -q && \
		git -C rpi-rgb-led-matrix fetch -q --depth 1 $(RGBMATRIX_REPO) $(RGBMATRIX_COMMIT) && \
		git -C rpi-rgb-led-matrix checkout -q FETCH_HEAD && \
		.venv/bin/pip install --prefer-binary "cython>=3" && \
		$(MAKE) -C rpi-rgb-led-matrix/lib && \
		$(MAKE) -C rpi-rgb-led-matrix/bindings/python/rgbmatrix CYTHON=$(CURDIR)/.venv/bin/cython && \
		.venv/bin/pip install --no-build-isolation ./rpi-rgb-led-matrix/bindings/python && \
		rm -rf rpi-rgb-led-matrix && \
		echo "✅ rgbmatrix installed."; \
	fi

rpi-optimize: check-rpi ## Raspberry Pi ONLY - Optimize matrix performance
	@if [ ! -f /etc/systemd/system/matrix.service ] || [ "$(filter rpi-optimize,$(MAKECMDGOALS))" != "" ]; then \
		if [ $$(grep -c ^processor /proc/cpuinfo) -ge 4 ]; then multicore=1; msg="reserve a CPU core for the display and disable onboard audio"; else multicore=0; msg="disable onboard audio"; fi; \
		read -p "⚠️ Would you like to $$msg to optimize performance? [Y/n]: " proceed; \
		if [ "$$proceed" != "y" ] && [ "$$proceed" != "Y" ]; then \
			echo "Optimization aborted. Feel free to use \\033[1;36mmake rpi-optimize\\033[0m to run this later."; \
		else \
			changed=0; \
			if [ $$multicore -eq 1 ] && ! grep -q "isolcpus=3" $(BOOT_DIR)/cmdline.txt; then \
				echo "⚙️  Adding isolcpus=3 to $(BOOT_DIR)/cmdline.txt..."; \
				sudo cp $(BOOT_DIR)/cmdline.txt $(BOOT_DIR)/cmdline.txt.tmp; \
				sudo sed -i 's/$$/ isolcpus=3/' $(BOOT_DIR)/cmdline.txt.tmp; \
				sudo mv $(BOOT_DIR)/cmdline.txt.tmp $(BOOT_DIR)/cmdline.txt; \
				echo "✅ isolcpus=3 added."; \
				changed=1; \
			fi; \
			if ! grep -q "^blacklist snd_bcm2835" /etc/modprobe.d/alsa-blacklist.conf 2>/dev/null; then \
				echo "⚙️  Blacklisting onboard audio (snd_bcm2835)..."; \
				echo "blacklist snd_bcm2835" | sudo tee -a /etc/modprobe.d/alsa-blacklist.conf > /dev/null; \
				echo "✅ snd_bcm2835 blacklisted."; \
				changed=1; \
			fi; \
			if ! grep -q "^dtparam=audio=off" $(BOOT_DIR)/config.txt; then \
				echo "⚙️  Disabling onboard audio in config.txt..."; \
				sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' $(BOOT_DIR)/config.txt || true; \
				if ! grep -q "^dtparam=audio=off" $(BOOT_DIR)/config.txt; then \
					echo "dtparam=audio=off" | sudo tee -a $(BOOT_DIR)/config.txt > /dev/null; \
				fi; \
				echo "✅ Onboard audio disabled."; \
				changed=1; \
			fi; \
			if [ $$changed -eq 1 ]; then \
				echo "🔄 Please reboot your Raspberry Pi for changes to take effect."; \
				echo "Note: You must run \033[1;36mmake run\033[0m after reboot to complete Spotify authorization!"; \
				echo ""; \
				read -p "Reboot now? [Y/n]: " ans; \
				if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
					echo "Rebooting..."; \
					sudo reboot; \
				else \
					echo "Reboot skipped. Remember to reboot manually later."; \
				fi; \
				exit 1; \
			fi; \
		fi; \
	fi

rpi-service: check-rpi ## Raspberry Pi ONLY - Set up systemd service and alias
	@if [ ! -f /etc/systemd/system/matrix.service ]; then \
		echo "⚙️ Installing systemd service to automatically run display at startup..."; \
		sed "s|__WORKING_DIR__|$(CURDIR)|g" matrix.service | sudo tee /etc/systemd/system/matrix.service > /dev/null; \
		echo "🔄 Reloading systemd..."; \
		sudo systemctl daemon-reload; \
		echo "🎉 Matrix service installed! This can be used after Spotify authorization is complete."; \
	fi
	@if ! grep -q "alias matrix=" ~/.bash_aliases 2>/dev/null; then \
		echo "⚡ Adding alias 'matrix' to ~/.bash_aliases..."; \
		echo "alias matrix='sudo service matrix'" >> ~/.bash_aliases; \
		. ~/.bash_aliases; \
		echo "✅ Done!"; \
		echo ""; \
	fi