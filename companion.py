#!/usr/bin/python3

# companion.py
# (c) Georg Sieber 2019
# github.com/schorschii

# this script emulates the functionality of the Atlassian Companion App (Windows/Mac) for usage on Linux clients
# please see README.md for installation instructions

# IMPORTANT NOTE: this script is currently EXPERIMENTAL and therefore not intended for productive usage!


from subprocess import check_output
from urllib.parse import urlparse
import asyncio
import pathlib
import ssl
import websockets
import json
import urllib.request
import subprocess
import time
import requests

ALLOWED_SITE = "Confluence" # please replace with your confluence site name to allow access
TRANSACTION_ID = "406905c8-13f5-42b1-a74f-4382f03a6053" # static transaction id
FILES = [] # temp storage for downloaded file metadata

async def handleJson(websocket, requestjson):
    global FILES
    responsejson = {}
    if(requestjson["type"] == "authentication"):
        if(requestjson["payload"]["payload"]["siteTitle"] == ALLOWED_SITE):
            print("ACCEPTED SITE: " + requestjson["payload"]["payload"]["siteTitle"])
            responsejson = {
                "requestID": requestjson["requestID"],
                "type": "authentication-status",
                "payload": "ACCEPTED"
            }
        else:
            print("REJECTED SITE: " + requestjson["payload"]["payload"]["siteTitle"])
            responsejson = {
                "requestID": requestjson["requestID"],
                "type": "authentication-status",
                "payload": "REJECTED"
            }
        await send(websocket, json.dumps(responsejson))

    elif(requestjson["type"] == "new-transaction" and requestjson["payload"]["transactionType"] == "file"):
        responsejson = {
            "requestID": requestjson["requestID"],
            "payload": TRANSACTION_ID
        }
        await send(websocket, json.dumps(responsejson))

    elif(requestjson["transactionID"] == TRANSACTION_ID and requestjson["type"] == "list-apps"):
        responsejson = {
            "requestID": requestjson["requestID"],
            "payload": [{
                "displayName": "Linux (yay!)",
                "imageURI": "",
                "id": "2a2fe73b2ed43010dba316046ce79923",
                "windowsStore": False
            }]
        }
        await send(websocket, json.dumps(responsejson))

    elif(requestjson["transactionID"] == TRANSACTION_ID and requestjson["type"] == "launch-file-in-app"):
        appId = requestjson["payload"]["applicationID"]
        transId = requestjson["transactionID"]
        fileUrl = requestjson["payload"]["fileURL"]
        fileName = requestjson["payload"]["fileName"]

        # store file info for further requests (upload)
        FILES.append({"transId":transId, "fileName":fileName})

        # inform confluence about that the download started
        responsejson = {
            "eventName": "file-download-start",
            "type": "event",
            "payload": appId,
            "transactionID": transId
        }
        await send(websocket, json.dumps(responsejson))

        # start download
        urllib.request.urlretrieve(fileUrl, fileName)

        # inform confluence that the download finished
        responsejson = {
            "eventName": "file-downloaded",
            "type": "event",
            "payload": None,
            "transactionID": transId
        }
        await send(websocket, json.dumps(responsejson))

        # get application path via xdg-mime from command line
        mimetype = check_output(["xdg-mime", "query", "filetype", fileName])
        application = check_output(["xdg-mime", "query", "default", mimetype.decode("utf-8").strip()])
        execinfo = check_output(["grep", "-m1", "^Exec=", "/usr/share/applications/"+application.decode("utf-8").strip()])
        executable = execinfo.decode("utf-8").replace("Exec=","").replace("%F","").strip()

        # start application and wait until closed
        subprocess.call([executable, fileName])
        print("editing ended")

        # inform confluence about the changes
        responsejson = {
            "eventName": "file-change-detected",
            "type": "event",
            "payload": appId,
            "transactionID": transId
        }
        await send(websocket, json.dumps(responsejson))

    elif(requestjson["transactionID"] == TRANSACTION_ID and requestjson["type"] == "upload-file-in-app"):
        transId = requestjson["transactionID"]
        fileUrl = requestjson["payload"]["uploadUrl"]

        # get stored file name
        fileName = None
        for f in FILES:
            if(f["transId"] == transId):
                fileName = f["fileName"]
                break

        # inform confluence that upload started
        responsejson = {
            "eventName": "file-direct-upload-start",
            "type": "event",
            "payload": {
                "fileID": requestjson["payload"]["fileID"],
                "directUploadId": 2
            },
            "transactionID": transId
        }
        await send(websocket, json.dumps(responsejson))

        print("Now uploading " + fileName + " to: " + fileUrl)
        parsed_uri = urlparse(fileUrl)
        host = '{uri.netloc}'.format(uri=parsed_uri)
        origin = '{uri.scheme}://{uri.netloc}'.format(uri=parsed_uri)
        headers = {
            "Host": host,
            "origin": origin,
            "Accept": None,
            "Accept-Language": "de",
            "X-Atlassian-Token": "nocheck"
            #"User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) AtlassianCompanion/0.6.2 Chrome/61.0.3163.100 Electron/2.1.0-unsupported.20180809 Safari/537.36"
        }
        with open(fileName, 'rb') as f:
            r = requests.post(
                fileUrl,
                files={
                    "comment": ("comment", "Uploaded by Companion for Linux (yay!)"),
                    "file": (fileName, f)
                },
                headers=headers
            )
            print(r)
            print(r.text)

        # inform confluence that upload finished
        responsejson = {
            "eventName": "file-direct-upload-progress",
            "type": "event",
            "payload": {
                "progress": { "percentage": 100 },
                "directUploadId": 2
            },
            "transactionID": transId
        }
        await send(websocket, json.dumps(responsejson))

        # inform confluence that upload finished
        responsejson = {
            "eventName": "file-direct-upload-end",
            "type": "event",
            "payload": {
                "fileID": requestjson["payload"]["fileID"],
                "directUploadId": 2
            },
            "transactionID": transId
        }
        await send(websocket, json.dumps(responsejson))

async def companionHandler(websocket, path):
    while(True):
        request = await websocket.recv()
        print(f"< {request}")
        await handleJson( websocket, json.loads(request) )

async def send(websocket, response):
    await websocket.send(response)
    print(f"> {response}")

ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_context.load_cert_chain('demo-cert/companion.crt', 'demo-cert/companion.key')

start_server = websockets.serve(
    companionHandler, "localhost", 22274, ssl=ssl_context
)

asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
