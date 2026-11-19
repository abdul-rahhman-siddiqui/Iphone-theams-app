@echo off
REM Right-click -> Run as administrator. Allows the iPhone to reach PhoneCam (TCP 8443).
netsh advfirewall firewall delete rule name="PhoneCam" >nul 2>&1
netsh advfirewall firewall add rule name="PhoneCam" dir=in action=allow protocol=TCP localport=8443 profile=private,domain
echo.
echo If your Wi-Fi is set to "Public", also set it to Private: Settings - Network - Wi-Fi - your network - Private.
pause
