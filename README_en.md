# [Русская версия](./README.md)

# Overlay for Distance Measurement in War Thunder

A small Python application (based on PyQt5) that adds a **semi-transparent overlay** on top of your screen to let you **measure distances in meters** in games or other software. Primarily designed for [War Thunder](https://warthunder.com/), it allows you to find out how far apart objects are by simply holding down the **right mouse button (RMB)**, without minimizing the game.

---

## Key Features

1. **Quick distance measurement (in meters)**  
   - Press and hold **RMB**, drag a line — the application shows its length.

2. **One-click calibration**  
   - After drawing your first line (or pressing `c`), a dialog prompts you to enter the real length (in meters).  
   - The application then learns how many meters correspond to one screen pixel.

3. **Global hotkeys**  
   - `=` — toggle measurement mode (RMB).  
   - `c` — reset calibration.  
   - `ctrl + shift + q` — quit the application.  
   - `-,=` or the **“Clear”** button — clear all drawn lines.

4. **Transparent window**  
   - **LMB** is not intercepted by the overlay, so you can still use it to interact with the game.  
   - **RMB** in measurement mode is used to draw lines on the overlay.

5. **Visual hints**  
   - Display line length, angle (0° = up, 90° = right), and useful messages.  
   - Provide quick shortcuts to recalibrate or clear drawn lines.

---

## Installation (Windows)

> **Note!** This app works only on Windows because it uses `pyWinhook` for the global mouse hook.

1. **Install Python 3.7 or higher** (3.9+ recommended).  
2. _(Optional)_ Create and activate a virtual environment:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```
3. **Install the required dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## Usage

### Run the Script
- Launch the script. You will see a semi-transparent window with on-screen hints.

### Enable Measurement Mode
- Press `=`. Now, holding **RMB** lets you draw lines instead of interacting with the game.

### Calibration
- On your first measurement (or after pressing `c`), a dialog will appear asking for the real distance (in meters) of the line you’ve just drawn.  
- The overlay calculates the **pixel-to-meter** ratio based on your input.

### Measurement
- Every time you press and hold **RMB** to draw a new line, its length and angle (relative to the vertical) will appear on-screen.

### Disable Measurement Mode
- Press `=` again to return to normal in-game mouse controls.

### Clear Lines
- Press `-,=` or click the **“Clear”** button on the overlay panel to remove all drawn lines.

### New Calibration
- Press `c` and draw a new line. The calibration dialog will open again, allowing you to re-enter the exact distance.

### Close the Overlay
- Press `ctrl + shift + q` to fully exit the application.