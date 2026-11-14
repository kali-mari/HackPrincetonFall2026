#!/usr/bin/env python3
"""Verify host UTC via two HTTPS servers, inspect/correct target clock over USB.
No packages, RTC writes, app database changes or reboot. Password is read via getpass.
"""
import argparse
import datetime as dt
import email.utils
import getpass
import json
from pathlib import Path
import subprocess
import time

REFERENCES = ['https://www.google.com/generate_204', 'https://www.cloudflare.com/cdn-cgi/trace']

def verified_host():
    observations = []
    for url in REFERENCES:
        t0 = time.time()
        r = subprocess.run(['curl', '--silent', '--show-error', '--fail', '--location', '--max-time', '15',
                            '-D', '-', '-o', '/dev/null', url+'?clock_nonce='+str(time.time_ns())],
                           text=True, capture_output=True, check=True)
        t1 = time.time()
        dates = [line.split(':', 1)[1].strip() for line in r.stdout.splitlines() if line.lower().startswith('date:')]
        stamp = email.utils.parsedate_to_datetime(dates[-1]).timestamp()
        offset = stamp-(t0+t1)/2
        if abs(offset) > 2 or t1-t0 > 3: raise RuntimeError('Host UTC did not pass reference check')
        observations.append(dict(source=url, tls_verification=True, http_date_utc=dates[-1],
                                 host_midpoint_epoch=(t0+t1)/2, server_minus_host_s=offset,
                                 request_roundtrip_s=t1-t0, uncertainty_s=1+(t1-t0)/2))
    return observations

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--adb', required=True); p.add_argument('--serial', required=True)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--output', default=str(Path(__file__).resolve().parent/'local/experiment2/clock.json'))
    a=p.parse_args(); base=[a.adb,'-s',a.serial,'shell']
    if Path(a.output).exists():raise RuntimeError('Refusing to overwrite previous clock evidence before any correction')
    def shell(command):
        r=subprocess.run(base+[command],capture_output=True,text=True,check=True)
        return r.stdout.strip()
    def snapshot():
        t0=time.time(); epoch=float(shell('date -u +%s.%N'));t1=time.time()
        return dict(utc=dt.datetime.fromtimestamp(epoch,dt.timezone.utc).isoformat(),epoch=epoch,
                    host_midpoint_epoch=(t0+t1)/2,board_minus_host_s=epoch-(t0+t1)/2,roundtrip_s=t1-t0,
                    timedatectl=shell('timedatectl'),sync_properties=shell('timedatectl show-timesync --all'),
                    rtc=shell('cat /sys/class/rtc/rtc0/name /sys/class/rtc/rtc0/since_epoch 2>/dev/null || true'),
                    saved_clock=shell('stat -c %y /var/lib/systemd/timesync/clock'))
    report={'reference_checks':verified_host(),'before':snapshot(),'reboot_persistence':'NOT TESTED',
            'rtc_battery_backing':'NOT ESTABLISHED','method':'inspection only',
            'automatic_sync_proven':False,'commands':[]}
    if a.apply:
        password=getpass.getpass('UNO Q sudo password (not saved): ')
        # Reverify immediately before setting the host-derived UTC, not a prompt date.
        report['reference_checks_before_apply']=verified_host()
        enable=subprocess.run(base+["sudo -S -p '' systemctl enable --now systemd-timesyncd"],input=password+'\n',capture_output=True,text=True)
        if enable.returncode: raise RuntimeError('Cannot enable existing time-sync service')
        report['reference_checks_before_set']=verified_host()
        epoch=time.time()
        command="sudo -S -p '' date -u --set=@"+f'{epoch:.6f}'
        r=subprocess.run(base+[command],input=password+'\n',capture_output=True,text=True)
        password=None
        if r.returncode: raise RuntimeError('Authorized clock correction failed; password not logged')
        report.update(method='manual UTC correction from HTTPS-verified host over USB; not proof of automatic sync',
                      commands=['systemctl enable --now systemd-timesyncd','date -u --set=@<verified-host-current-epoch>'],
                      requested_epoch=epoch,apply_output=r.stdout.strip())
        report['after']=snapshot()
        report['automatic_sync_proven']='System clock synchronized: yes' in report['after']['timedatectl']
        report['utc_reliable_after']=abs(report['after']['board_minus_host_s'])<2
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if out.exists():raise RuntimeError('Refusing to overwrite previous clock evidence')
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'method':report['method'],'before_offset_s':report['before']['board_minus_host_s'],
                      'after':report.get('after'),'reboot_persistence':'NOT TESTED'},indent=2))

if __name__=='__main__':main()
