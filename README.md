<div align="center">
  <img src="images/demo.gif" width="256" alt="Demo">
  <h1>rpi-spotify-matrix-display</h1>
  <p>A Spotify display for 64x64 RGB LED matrices.<br>Run on a Raspberry Pi connected to a matrix, or just play around using the emulator!</p>
  <a href="https://www.buymeacoffee.com/kylejohnsonkj"><img src="https://raw.githubusercontent.com/pachadotdev/buymeacoffee-badges/main/bmc-yellow.svg" alt="BuyMeACoffee"></a>
</div>

## 🪶 Lite

This version of the display is made to run well on small Pis such as the Pi Zero:

- Runs on Python 3.9+ (Raspberry Pi OS Bullseye and newer) with fewer dependencies. The emulator packages are only installed on non-Pi machines.
- Uses less CPU: it downloads the smallest album art that covers the matrix, only redraws when something on screen changes, and can poll Spotify less often while nothing is playing.
- Adds display controls (brightness, contrast, saturation and color profile), [Home Assistant](#-home-assistant) support and a [settings page](#-settings-page) for setup without SSH.
- Includes a small built-in client, so [lyrics](#-lyrics-support) work without LibreLyrics.

## 🔑 Spotify Setup
1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app _(name/description can be anything)_
3. Add http://127.0.0.1:8080/callback to Redirect URIs
4. Save and copy the Client ID and Secret for later

## 📦 Installation

```bash
git clone https://github.com/kylejohnsonkj/rpi-spotify-matrix-display

cd rpi-spotify-matrix-display

make          # The Makefile does it all for you!
```

## ▶ Running the Display

```bash
make emulate  # Run in emulator (macOS, Windows, etc. - no external hardware required)
make run      # Run on a pi connected to an LED matrix display

make help     # List available commands
```

After starting the display, follow the instructions in the console. The pasted link should begin with http://127.0.0.1:8080/callback. After successful authorization, play a song and the display will appear! ✅

### Running in the background

`make run` also installs a systemd service. Once Spotify is authorized, start the display on every boot with:

```bash
sudo systemctl enable --now matrix
```

Then use `matrix start`, `matrix stop`, `matrix restart` and `matrix status` to control it. The service waits for the network and restarts the display if it crashes. Logs are written to `matrix.log`.

If the service was installed by an older version, reinstall it to get the automatic restart: `sudo rm /etc/systemd/system/matrix.service && make rpi-service`, then run `sudo systemctl daemon-reload`.

With the [settings page](#-settings-page) enabled, Spotify can also be authorized from the browser, without a terminal.

---

## 🎵 Lyrics Support

The display supports two methods of displaying lyrics. You can choose your preference by setting `dedicated_lyrics` to true or false in the configuration file.

Lyrics are off by default. To show them, set `lyrics = true` under `[Spotify]` and provide your `sp_dc` cookie. `lyrics_provider` picks how they're fetched:

- `builtin` (default): a small built-in client that only needs `requests` and works on Python 3.9
- `librelyrics`: the [LibreLyrics](https://github.com/libre-lyrics/librelyrics) library (Python 3.10+, install it with `.venv/bin/pip install -e '.[librelyrics]'`). It may pick up fixes sooner when Spotify changes its login

| Standard Lyrics (default) | Dedicated Lyrics |
| --- | --- |
| <img src="images/standard.gif" width="256"> | <img src="images/dedicated.gif" width="256"> |

## 🧩 Configuration

You can configure the display using the `config.ini` or the [settings page](#-settings-page). Use it to update your [hardware mapping](https://github.com/hzeller/rpi-rgb-led-matrix#changing-parameters-via-command-line-flags) (may be required), opt for fullscreen artwork, adjust timings, or permit only certain playback devices to activate the display.

The display settings under `[Matrix]` are:

- `brightness`: 1-100
- `contrast` and `saturation`: 0-200 (100 is unchanged, and a saturation of 0 is grayscale)
- `color_profile`: Neutral, Warm, Cool or Night

These are starting values. Changes made from Home Assistant or the settings page are saved to `settings.json` and take priority over them. Delete `settings.json` to go back to the `config.ini` values.

**Tips for a Pi Zero**

- `target_fps = 30` halves the drawing work compared to the default of 60
- `idle_fetch_interval = 5` under `[Spotify]` polls Spotify every 5 seconds while nothing is playing (by default it uses `fetch_interval`)
- `gpio_slowdown = 0` or `1` usually works, since the Pi Zero is slower than other Pis. Raise it if the display flickers

## 🏠 Home Assistant

The display can be controlled from Home Assistant over MQTT. You need an MQTT broker: the Mosquitto broker add-on, or the `eclipse-mosquitto` Docker image if you run Home Assistant Container. Add the MQTT integration in Home Assistant, then set `enabled = true` and your broker details under `[HomeAssistant]` in `config.ini`. The display is added automatically as a device with:

- **Light**: turn the display on/off and set its brightness
- **Contrast**: 0-200% (100% is unchanged)
- **Saturation**: 0-200% (0% is grayscale, 100% is unchanged)
- **Color profile**: Neutral, Warm, Cool or Night

Changes made from Home Assistant and from the settings page stay in sync, and are restored after a restart.

## 🌐 Settings page

To change settings without SSH, set `enabled = true` under `[Web]` in `config.ini` and restart the display. Then open `http://<pi address>:8000` from any device on your network to:

- Adjust the same display controls Home Assistant has
- Edit `config.ini` settings (saving restarts the display to apply them)
- Authorize Spotify: open the link, approve, then paste the address of the `127.0.0.1` page that fails to load

On a fresh install, the display creates `config.ini` from `config.ini.example` with the page already enabled, so setup can be finished in the browser at `http://<hostname>.local:8000` (the address is also logged).

Secrets such as the client secret are never shown on the page. Set `password` under `[Web]` to require a password, and don't expose the page outside your network.

If the address shows another web server's page (such as "Welcome to nginx"), check that it includes the port `:8000`. Set `port` under `[Web]` to use a different one.

## 💬 FAQ

<details>
<summary><b>Can I use this with a matrix other than 64x64?</b></summary>

Only 64x64 matrices are supported at this time. If you'd like to extend this project to support other matrix sizes, feel free to fork this project!
</details>

<details>
<summary><b>I'm not seeing the right album artwork.</b></summary>

Spotify is likely set to video playback mode and is sending a still from the video. Switch back to audio playback in your Spotify app.
</details>

<details>
<summary><b>Where do I get my `sp_dc` for lyrics?</b></summary>

[See this guide](https://github.com/akashrchandran/syrics/wiki/Finding-sp_dc) to find your sp_dc cookie, then set `lyrics = true` under `[Spotify]`. Skip this step if you do not want to show lyrics.

The cookie stops working if you log out of the browser session you copied it from, so close that window instead of logging out.
</details>

<details>
<summary><b>Why are lyrics sometimes delayed or out of sync?</b></summary>

When playing to a Spotify Connect destination, lyrics may start out delayed due to the API not accounting for how long the destination took to connect. This is automatically resolved after about 30s of listening, when the API figures out what happened. You can see the same behavior with Spotify's own lyrics screen as well. Additionally, some songs are synced better than others.
</details>

<details>
<summary><b>The display crashed with "OverflowError: can't convert negative value to size_t".</b></summary>

This is a bug in rgbmatrix builds from older versions of this project, and it happens on 32-bit Pis such as the Pi Zero. The display now works around it by copying those frames slowly, so rebuild the library to fix it properly:

```bash
matrix stop
.venv/bin/pip uninstall -y rgbmatrix && make rpi-rgbmatrix
matrix start
```
</details>

<details>
<summary><b>Why does the API get called every second?</b></summary>

Spotify's API does not provide public websocket support, so the only way to determine playback status and track progression is by polling the API regularly. You can increase this polling interval in `config.ini` if you want to reduce the number of calls, or set `idle_fetch_interval` to poll less often only while nothing is playing.
</details>

---

## 🛠️ Building Your Own Display

Don't have a Raspberry Pi or LED matrix yet? No worries! Play around with the emulator and come back to this section once you're ready.

**Parts List**

- [Adafruit 64x64 RGB LED Matrix - 2.5mm Pitch - 1/32 Scan](https://www.adafruit.com/product/3649)
- [Adafruit RGB Matrix Bonnet for Raspberry Pi](https://www.adafruit.com/product/3211)
- [Raspberry Pi 3B+](https://www.raspberrypi.com/products/raspberry-pi-3-model-b-plus/) (or newer; a Pi Zero also works using 32-bit Raspberry Pi OS Lite, Python 3.9+)
- Any microSD card
- [5V 10A Power Supply Adapter](https://www.amazon.com/gp/product/B08HCS1X66)

I also 3d printed a [matrix stand](https://www.thingiverse.com/thing:3781875) and a [pi mount](https://www.thingiverse.com/thing:2732552) for my [own build](https://imgur.com/a/64x64-album-art-matrix-backside-AjrOa5e).

Once you have all the parts, proceed with the Rasperry Pi Setup below!

<details>
<summary><b>⚙️ Raspberry Pi Setup</b></summary>

#### Step 1: Install Pi OS
- [Download and open the Raspberry Pi Imager](https://www.raspberrypi.com/software/)
    - Select your Raspberry Pi
    - Select `Raspberry Pi OS (other) - Raspberry Pi OS Lite (64-bit)`, or the 32-bit version for an original Pi Zero / Zero W, which can't run 64-bit
    - Select your microSD card
- Tap "Next" and edit OS customization settings
    - Set hostname (I put matrix), set user/pass (I kept user as pi)
    - Enter wifi credentials
    - Enable ssh using password authentication
- When done, insert microSD card in pi and wait a few min for boot up

#### Step 2: Login via ssh
- `ssh pi@matrix.local`
- This puts you in the `/home/pi` directory
- You can use `pwd` to confirm where you are throughout this process

#### Step 3: Install git
- `sudo apt install git`

#### Step 4: Follow the [Installation](#-installation) guide
- Soon you'll be seeing something like this!

https://github.com/user-attachments/assets/9bf163f9-8e0f-47cc-b2d2-a62b3a975471

</details>

---

## :heart: Acknowledgements
- **allenslab** for inspiring this project with the original [matrix-dashboard](https://www.reddit.com/r/3Dprinting/comments/ujyy4g/i_designed_and_3d_printed_a_led_matrix_dashboard/)
- **typorter** for his continued work on [RGBMatrixEmulator](https://github.com/ty-porter/RGBMatrixEmulator)
- **spotipy contributors** for the Spotify Web API [python wrapper](https://github.com/spotipy-dev/spotipy)
- **akashrchandran** for [LibreLyrics](https://github.com/libre-lyrics/librelyrics) (and specifically the Spotify [plugin](https://github.com/libre-lyrics/librelyrics-spotify), which the built-in lyrics client is ported from)
- **ThetaDev** for the [spotify-secrets](https://code.thetadev.de/ThetaDev/spotify-secrets) list the lyrics client uses
- **Eclipse Paho** for the Python [MQTT client](https://github.com/eclipse-paho/paho.mqtt.python)
- **hzeller** for the essential [rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) library