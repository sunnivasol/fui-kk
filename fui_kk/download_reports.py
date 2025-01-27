#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Downloads TSV and HTML reports for a user from nettskjema.uio.no"""

__authors__    = ["Erik Vesteraas"]
__copyright__  = "Erik Vesteraas"
__license__    = "MIT"
# This file is subject to the terms and conditions defined in
# file 'LICENSE.txt', which is part of this source code package.

# Dependencies:
# pip install selenium
# pip install requests
# brew install phantomjs

# Login and forms system requires javascript, so we use selenium to login and
# browse the page.
# Downloading files with selenium is not very convenient, so we use requests
# for that particular part.
# PhantomJS is the engine we use for selenium.

import getpass
import os
import sys
import locale
import argparse
import json
import re
import pickle
import requests
from selenium import webdriver

from file_funcs import path_join, path_clean, filename_clean

def get_args():
    argparser = argparse.ArgumentParser(description='Download report data from nettskjema.uio.no')
    argparser.add_argument('--out', '-o', help='Output directory (default="./downloads")', type=str, default='./downloads')
    argparser.add_argument('--filter', '-f', help='String to filter by', type=str)
    argparser.add_argument('--username', '-u', help='Username for login', type=str)
    argparser.add_argument('--password', '-p', help='Password for login', type=str)
    argparser.add_argument('--tsv', help='Download TSV files', action="store_true")
    argparser.add_argument('--html', help='Download HTML reports', action="store_true")
    argparser.add_argument('--stats', help='Download answer statistics', action="store_true")
    args = argparser.parse_args()

    if not (args.tsv or args.html or args.stats):
        args.tsv = True
        args.html = True
        args.stats = True

    if not args.username:
        args.username = input('Username: ')

    if not args.password:
        args.password = getpass.getpass()

    return args

def login(driver, args):
    driver.get('https://nettskjema.uio.no/user/index.html')

    userfield = driver.find_element_by_css_selector('#username')
    userfield.send_keys(args.username)

    passfield = driver.find_element_by_css_selector('#password')
    passfield.send_keys(args.password)

    button = driver.find_element_by_css_selector('#login-box-form .submit')
    button.click()

def write_to_file(folder, name, extension, content):
    if not os.path.exists(folder):
        os.makedirs(folder)
    filename = path_join(folder, name) + '.' + extension
    filename = path_clean(filename)
    with open(filename, 'w', encoding="utf-8") as f:
        f.write(content)

def try_to_find_int(driver, selector):
    try:
        return int(driver.find_element_by_css_selector(selector).text)
    except:
        return 0

def render_html(name, stats, content):
    return '''
    <html>
        <head>
            <meta charset="utf-8" />
        </head>
        <body>
            <p>Delivered replies: {answered}</p>
            <p>Commenced replies: {started}</p>
            <p>Number of sent invitations: {invited}</p>
            <hr />
            <h1>{title}</h1>
            {content}
        </body>
    </html>
    '''.format(
        title=name,
        content=content,
        answered=stats['answered'],
        started=stats['started'],
        invited=stats['invited']
    )

def get_id(url):
    p = re.compile("id=[0-9]{1,10}")
    m = p.search(url)
    if m is None:
        return ""
    return m.group(0)[3:]

def read_list(path):
    try:
        with open(path, 'r') as f:
            return f.read().split("\n")
    except FileNotFoundError:
        return []

def read_binary(path):
    try:
        with open (path, 'rb') as fp:
            return pickle.load(fp)
    except FileNotFoundError:
        return None

def write_binary(path, data):
    folder = os.path.dirname(path)
    if not os.path.exists(folder):
        os.makedirs(folder)
    with open(path, 'wb') as fp:
        pickle.dump(data, fp)

def os_encode(msg):
    os_encoding = locale.getpreferredencoding()
    return msg.encode(os_encoding)

def error(msg, exception=None, *, label=None):
    if label:
        print("\n***FUI-KK ERROR: {}***".format(label))
    else:
        print("\n***FUI-KK ERROR***")
    if exception:
        print("Exception: {}\n".format(type(exception)))
    print(msg)
    sys.exit(-1)

def download_files(driver, args):
    downloaded = read_list(args.out+"/downloaded.txt")

    formdata = read_binary(args.out+"/formdata.dat")
    if not formdata:
        driver.get('https://nettskjema.uio.no/user/form/list.html')
        forms = driver.find_elements_by_css_selector('.forms .formName')
        formdata = [(form.text, form.get_attribute('href')) for form in forms]
        write_binary(args.out+"/formdata.dat",formdata)

    if args.filter:
        filtered = [x for x in formdata if args.filter in x[0]]
        print('Filter matched {} of {} forms'.format(len(filtered), len(formdata)))
        formdata = filtered

    session = requests.Session()
    cookies = driver.get_cookies()
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'])
    out_path = path_clean(args.out)
    tsv_path = path_join(out_path, 'tsv')
    html_path = path_join(out_path, 'html')
    stats_path = path_join(out_path, 'stats')

    for (name, url) in formdata:
        form_id = get_id(url)

        try:
            if form_id in downloaded:
                print("Skipping {} (id={})".format(name,form_id))
                continue
            print("Fetching {} (id={})".format(name,form_id))
        except UnicodeEncodeError as e:
            # NOTE: This error can be fixed by using os_encode on name,
            #       however I think it is useful to force windows users
            #       to change to utf-8, just in case wrong encoding
            #       causes problems elsewhere.
            error_msg = "\n".join([
            "Form id={}".format(form_id),
            "Form name: {}".format(os_encode(name)),
            "Your terminal probably doesn't like unicode.",
            "To fix this on windows, change codepage using this command:",
            "chcp 65001"
            ])
            error(error_msg, e, label="Non-unicode codepage")
        results_url = url.replace('preview', 'results')
        driver.get(results_url)
        stats = {
            'answered': try_to_find_int(driver, '.delivered-submissions .number'),
            'started': try_to_find_int(driver, '.saved-submissions .number'),
            'invited': try_to_find_int(driver, '.valid-invitations .number')
        }
        name_cleaned = filename_clean(name)
        if args.tsv:
            tsv_url = url.replace('preview', 'download') + '&encoding=utf-8'
            response = session.get(tsv_url)
            write_to_file(tsv_path, name_cleaned, 'tsv', response.text)

        if args.html:
            html_url = url.replace('preview', 'report/web') + '&include-open=1&remove-profile=1'
            response = session.get(html_url)
            write_to_file(html_path, name_cleaned, 'html', render_html(name, stats, response.text))

        if args.stats:
            stats_json = json.dumps(stats)
            write_to_file(stats_path, name_cleaned, 'json', stats_json)

        with open(args.out+"/downloaded.txt", 'a') as f:
            f.write(form_id+"\n")

def main():
    args = get_args()

    driver = webdriver.PhantomJS()
    driver.set_window_size(800, 600)

    try:
        login(driver, args)
        download_files(driver, args)
    except requests.exceptions.TooManyRedirects as e:
        error("Sometimes nettskjema doesn't like us.\n"\
              "Just wait a little while and continue\n"\
              "by rerunning script.", e, label="Nettskjema")
    finally:
        driver.close()
        driver.quit()

if __name__ == '__main__':
    main()
