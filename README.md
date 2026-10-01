# AirKeys

Use the keyboard on a MacBook to type on a PC that is on the same Wi-Fi.

The keyboard side runs on macOS. The receiving side runs on Windows, Linux, or another Mac. The trackpad stays on the Mac. Keys are sent only while sharing is turned on, and the window stays on screen so it is obvious when that is happening.

## Why this is not Bluetooth

macOS does not let an app pretend to be a Bluetooth keyboard. Wi-Fi on the same home network is the path that works. On a normal LAN the delay is a few milliseconds, which is fine for typing.

## If you want the cursor to slide between screens

Deskflow and Input Leap already share a mouse and keyboard by letting the pointer leave one monitor and enter the other. Use those if both computers are in use and each has its own input.

AirKeys is for the other case. The PC has no keyboard, you are looking at the PC, and the MacBook in front of you is the keyboard.

## Set up the PC once

You need a keyboard for this install. After that, the receiver can start with Windows and wait on the monitor.

1. Install Python 3 from python.org and enable the option that adds Python to PATH.
2. Copy this folder to the PC.
3. Double-click `run-receiver.bat`.
4. When Windows asks, allow Python on private networks.
5. Leave the window open. It shows a PIN and an address.

To start it at sign-in, press Win+R, run `shell:startup`, and put a shortcut to `run-receiver.bat` in that folder.

## Set up the Mac

You need Python 3 on the Mac. `python3` has to be on your PATH. The Accessibility permission is granted to that exact program, so use the same one you launch AirKeys with.

1. Double-click `AirKeys.command`.
2. Choose "This MacBook is the keyboard".
3. If macOS asks for Accessibility access, turn it on for the app it names. If no prompt appears, open System Settings, Privacy & Security, Accessibility, and add the Python path shown in the AirKeys window.
4. Pick the PC in the list, or type the address shown on the PC.
5. Type the PIN shown on the PC.
6. Connect, then start sharing.

Stop with the trackpad. The button stays on screen. Control+Option+K also stops sharing.

You can also run it from Terminal:

```
cd airkeys
PYTHONPATH=src python3 -m airkeys
```

Check the permission without opening the window:

```
PYTHONPATH=src python3 -m airkeys doctor
```

## Same layout on both machines

AirKeys sends the physical key you pressed. The PC then applies its own keyboard layout. If both machines use US QWERTY, you get the character you expect. If the layouts differ, you get whatever that key means on the PC.

Command is sent as Ctrl, so Command+C copies on Windows. The checkbox in the window turns that off.

Symbols that you type with the Option key on a Mac are not translated. Those are Mac-only.

On a MacBook, the function row sends F1 through F12 when "Use F1, F2, etc. keys as standard function keys" is on in System Settings. Otherwise those keys stay on the Mac as brightness and media keys.

## Try it on the Mac alone

Open two AirKeys windows. In one, choose the computer that needs a keyboard. In the other, choose the MacBook keyboard, connect to `127.0.0.1`, and enter the PIN from the first window. Click into TextEdit, start sharing, and type. The keys go out over the network and come back. Stop sharing before you close the windows.

## Security

The PIN stops a random device on the network from connecting. Wrong PINs are slowed down, and eight failures lock that address out for a minute. The keystrokes themselves are not encrypted. Use this on a home network you trust, not on cafe Wi-Fi, and not on a guest network that blocks devices from seeing each other.

Sharing starts off. The window title changes to "AirKeys sharing" while it is on.

## Tests

```
cd airkeys
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Layout of the code

`grab_mac.py` watches the Mac keyboard. `route.py` decides which events to send. `link.py` is the TCP session on port 47777. `discover.py` finds the other computer with a UDP probe on port 47778. `inject.py` types on the receiving computer, using scan codes on Windows. `ui.py` is the window.

## License

MIT. See LICENSE.
