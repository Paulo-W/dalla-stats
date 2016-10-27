import argparse
import requests
import base64
import time
import os
from os import listdir
from os.path import isfile, join
import csv
import datetime
import logging
import sys

def main():
    version = 'v0.1-dev'

    parser = argparse.ArgumentParser()

    parser.add_argument("-u", "--username", default='', help="the router admin username")
    parser.add_argument("-p", "--password", default='', help="the router admin password")
    parser.add_argument("-i", "--interval", type=int, default=60, help="the interval in seconds to update the statistics.")
    parser.add_argument("-d", "--root-directory", default='.', help="directory to save logs")
    parser.add_argument("-l", "--disable-logging", default=False, action='store_true', help="Disable logging of statistics")
    parser.add_argument('-v', '--version', action='version', version='%(prog)s ' + version)

    args = parser.parse_args()

    if (args.username == '' or args.password == ''):
        print('[ERROR] Please supply username and password')
        exit()

    rootDir = args.root_directory

    timeKey = int(time.time())
    #month = time.localtime(timeKey).tm_mon
    counter = 0

    month = 1
    oldMonth = month

    dirStruct = getDirStructure(rootDir, month)
    userMap = loadUserMap(dirStruct['userMapFile'])

    session = initSession(args.username, args.password)

    oldStats = loadDeviceCache(dirStruct['cacheFile'])

    delta = []

    print('[INFO] Starting Dalla-Stats ' + version)

    abort = False

    while (True):
        try:
            timeKey = int(time.time())
            # month = time.localtime(timeKey).tm_mon

            print('[INFO] Getting device records @ ' + str(timeKey))

            deviceStats = getDeviceRecords(session)

            if (len(deviceStats) != 0):
                delta = calculateDeviceDeltas(oldStats, deviceStats)

                mergeDevices(oldStats, delta)

                if (oldMonth != month):
                    print('[INFO] We have entered a new month! Reset statistics...')
                    dirStruct = getDirStructure(rootDir, month)
                    # TODO: Go through each device and set on and off peak counters to delta

                    oldMonth = month

                saveDeviceCache(delta, dirStruct['cacheFile'])

                userStats = getUserStats(delta, userMap)
                total = getTotalStats(userStats)
                saveSummary(userStats, total, dirStruct['summaryFile'])

                oldStats = delta

                if (args.disable_logging == False):
                    logDeviceStats(delta, dirStruct['deviceDir'])
                    logUserStats(userStats, dirStruct['userDir'])
                    logTotalStats(total, dirStruct['totalFile'])

            if (args.interval == 0):
                break

            if (abort == False):
                time.sleep(args.interval)
            else:
                break

            counter = counter + 1

            if counter == 5:
                month = month + 1
                counter = 0

        except KeyboardInterrupt:
            print('\n[INFO] Exiting. Please wait...')
            time.sleep(1)
            abort = True
        except:
            print('[ERROR] Unexpected exception!')
            print(sys.exc_info()[0])

            print('[INFO] Logging out')
            logout(session)

def getDirStructure(rootDir, month):
    dirStruct = {}

    dirStruct['userMapFile'] = rootDir + '/user-map.csv'
    dirStruct['logDir'] = rootDir + '/logs/' + str(month)
    dirStruct['cacheFile'] = dirStruct['logDir'] + '/cache.csv'
    dirStruct['deviceDir'] = dirStruct['logDir'] + '/devices'
    dirStruct['userDir'] = dirStruct['logDir'] + '/users'
    dirStruct['summaryFile'] = dirStruct['logDir'] + '/summary.csv'
    dirStruct['totalFile'] = dirStruct['logDir'] + '/total.csv'

    return dirStruct

def saveSummary(users, total, summaryFile):
    compact = True

    if not os.path.exists(os.path.dirname(summaryFile)):
        os.makedirs(os.path.dirname(summaryFile))

    overviewFile = open(summaryFile, 'w')

    # TODO: Sort users based on actual total

    if (compact == True):
        overviewFile.write('Name, Total, On-Peak, Off-Peak\n')
        overviewFile.write('TOTAL, ' + str(total['On-Peak'] + total['Off-Peak']) + ', ' + str(total['On-Peak']) + ', ' + str(total['Off-Peak']) + '\n')

        for userDict in users:
            overviewFile.write(userDict['Name'] + ', ' + str(userDict['On-Peak'] +
            userDict['Off-Peak']) + ', ' + str(userDict['On-Peak']) + ', ' + str(userDict['Off-Peak']) + '\n')
    else:

        overviewFile.write('=======\nTOTAL\n=======\n')
        overviewFile.write('Total    : ' + str(total['On-Peak'] + total['Off-Peak']) + '\n')
        overviewFile.write('On-Peak  : ' + str(total['On-Peak']) + '\n')
        overviewFile.write('Off-Peak : ' + str(total['Off-Peak']) + '\n')

        overviewFile.write('=======\nUSERS\n=======\n')

        for userDict in users:
            overviewFile.write('--------\n' + userDict['Name'] + "\n--------\n")
            overviewFile.write('Total    : ' + str(userDict['On-Peak'] + userDict['Off-Peak']) + '\n')
            overviewFile.write('On-Peak  : ' + str(userDict['On-Peak']) + '\n')
            overviewFile.write('Off-Peak : ' + str(userDict['Off-Peak']) + '\n\n')

    overviewFile.close()

def saveDeviceCache(deviceStatsArray, cacheFile):
    """Save the given dict array to file
    """

    if (not os.path.exists(os.path.dirname(cacheFile))):
        os.makedirs(os.path.dirname(cacheFile))

    output = open(cacheFile, 'w')

    output.write('MAC Address, IP Address, Time,Total Bytes, Delta, On-Peak, Off-Peak\n')

    for device in deviceStatsArray:
        output.write('{0}, {1}, {2}, {3}, {4}, {5}, {6}\n'.format(device['MAC Address'],
        device['IP Address'], device['Time'], device['Total Bytes'], device['Delta'],
        device['On-Peak'], device['Off-Peak']))

    output.close()

def loadDeviceCache(cacheFile):
    """Load the device summary into a dict array
    """

    """
    MAC Address, IP Address, Time, Total Bytes, Delta, On-Peak, Off-Peak
    """

    deviceStats = []

    if (os.path.isfile(cacheFile) == False):
        return []

    inputFile = open(cacheFile, 'r')
    reader = csv.reader(inputFile, delimiter=',', skipinitialspace=True)

    for row in reader:
        if (reader.line_num != 1):
            tmpDevice = {}

            tmpDevice['MAC Address'] = row[0]
            tmpDevice['IP Address'] = row[1]
            tmpDevice['Time'] = row[2]
            tmpDevice['Total Bytes'] = int(row[3])
            tmpDevice['Delta'] = int(row[4])
            tmpDevice['On-Peak'] = int(row[5])
            tmpDevice['Off-Peak'] = int(row[6])

            deviceStats.append(tmpDevice)

    inputFile.close()
    return deviceStats

def mergeDevices(oldDevices, newDevices):
    """
    When a device is removed from the router we do not want to lose track of it
    """

    # Go through all the old devices
    # If it was not found in the newDevices, add it

    tmpAdd = []

    for old in oldDevices:
        # Does it exist in newDevices?
        found = False
        for new in newDevices:
            if (old['MAC Address'] == new['MAC Address']):
                if (old['IP Address'] == new['IP Address']):
                    found = True

        if (found == False):
            tmpAdd.append(old)

    for add in tmpAdd:
        #print('Device not found in new records, adding it now:')
        #print(add)
        newDevices.append(add)

def initDevices(statsDictArray, timeKey):
    """Strip invalid entries and parse valid entries
    """

    newDictArray = []

    for statsDict in statsDictArray:
        # Skip invalid intries
        if (len(statsDict) == 12):
            # Strip extra data,
            # Convert Dec IP to readable IP
            tmpDict = { 'MAC Address': statsDict['macAddress'],
                        'IP Address': decStrToIpStr(statsDict['ipAddress']),
                        'Total Bytes': int(statsDict['totalBytes']),
                        'Time': timeKey,
                        'Delta': -9999999999,
                        'On-Peak': -9999999999,
                        'Off-Peak': -9999999999}

            newDictArray.append(tmpDict)

    return newDictArray


def getDeviceRecords(session):
    """ Poll the router for the current device statistics

    These records need to be compared to a previous set to calculate the
    Delta
    """

    timeKey = int(time.time())

    # Configure page specific headers
    url = 'http://192.168.1.1/cgi?1&5'
    session.headers.update({'Referer': 'http://192.168.1.1/mainFrame.htm'})
    data ='[STAT_CFG#0,0,0,0,0,0#0,0,0,0,0,0]0,0\r\n[STAT_ENTRY#0,0,0,0,0,0#0,0,0,0,0,0]1,0\r\n'

    try:
        r = session.post(url=url, data=data, timeout=1)
    except requests.ConnectionError:
        print('[ERROR] Network unreachable!')
        return {}
    except requests.ReadTimeout:
        print('[ERROR] Connection timeout!')
        return {}
    except KeyboardInterrupt:
        #print('[ERROR] KeyboardInterrupt during getDeviceRecords()')
        raise
    except:
        print('[ERROR] Unexpected error: ', sys.exc_info()[0])
        return {}

    rawStats = r.text

    error = rawStats.split('\n')

    if (error[-1] != '[error]0'):
        print('[ERROR] Failed to get device records from router!')
        if (r.text == '<html><head><title>500 Internal Server Error</title></head><body><center><h1>500 Internal Server Error</h1></center></body></html>'):
            print('\t Another admin has logged in!')
        else:
            print('\t' + r.text)

        return []

    dictArray = []
    tmpDict = {}

    arr = rawStats.split("\n")

    for i in range(0, len(arr)):
        """
        Loop through every line
        If the line is a title
            begin split and read into dict

        if we encounter another title
            insert old dict into array and start new dict and increase index

        """

        arr[i] = arr[i].strip()

        # start of a new header
        if (arr[i][0] == '['):

            dictArray.append(tmpDict)
            tmpDict = {}
            next # skip the header

        tmp = arr[i].split('=')

        # Add key=value
        if (len(tmp) == 2):
            tmpDict[tmp[0]] = tmp[1]

    # Manipulate dict array to get what we need
    init = initDevices(dictArray, timeKey)

    logout(session)

    return init

def classifyDelta(deviceDict):
    """Given a device record, classift the delta
    """

    # init values
    if (deviceDict['On-Peak'] < 0):
        deviceDict['On-Peak'] = 0

    if (deviceDict['Off-Peak'] < 0):
        deviceDict['Off-Peak'] = 0

    localTime = time.localtime(deviceDict['Time'])

    if (localTime.tm_hour < 6):
        deviceDict['Off-Peak'] = deviceDict['Off-Peak'] + deviceDict['Delta']
    else:
        deviceDict['On-Peak'] = deviceDict['On-Peak'] + deviceDict['Delta']

def calculateDeviceDeltas(oldDeviceDeltas, currentDeviceRecords):

    localCurrent = currentDeviceRecords

    # Go through each new device entry
    for newDeviceDict in localCurrent:

        # search for matching device in old devices
        found = False

        for oldDeviceDict in oldDeviceDeltas:

            # look for match
            if (oldDeviceDict['MAC Address'] == newDeviceDict['MAC Address']):
                if (oldDeviceDict['IP Address'] == newDeviceDict['IP Address']):
                    found = True

                    # Historic device
                    if (oldDeviceDict['Time'] == newDeviceDict['Time']):
                        break

                    # Inherit counters
                    newDeviceDict['On-Peak'] = oldDeviceDict['On-Peak']
                    newDeviceDict['Off-Peak'] = oldDeviceDict['Off-Peak']

                    newDeviceDict['Delta'] = newDeviceDict['Total Bytes'] - oldDeviceDict['Total Bytes']

                    if (newDeviceDict['Delta'] < 0):
                        print(str(datetime.datetime.now()) + ' [WARN] Device has negative delta! Fixing...')
                        newDeviceDict['Delta'] = newDeviceDict['Total Bytes']

                        print(oldDeviceDict)
                        print('')

                    classifyDelta(newDeviceDict)

        # No matching old dict was found
        if (found == False):
            print('[INFO] New device found. Initializing records:')

            newDeviceDict['Delta'] = newDeviceDict['Total Bytes']
            classifyDelta(newDeviceDict)

            print(newDeviceDict)
            print('')

    return localCurrent

def logDeviceStats(statsDictArray, deviceDir):
    """Save device dict array to log files
    """
    """
    filename: M-A-C_I.P
    Time, Total Bytes, Delta, On-Peak, Off-Peak
    """

    if (not os.path.exists(deviceDir)):
        os.makedirs(deviceDir)

    for statsDict in statsDictArray:
        # Generate file name
        mac = statsDict['MAC Address'].replace(':', '-')
        ip = statsDict['IP Address']
        fileName = str(deviceDir + '/' + mac + '_' + ip + '.csv')

        # csv fields
        timeKey = statsDict['Time']
        totalBytes = statsDict['Total Bytes']
        delta = statsDict['Delta']
        peak = statsDict['On-Peak']
        offPeak = statsDict['Off-Peak']

        # new device, set up csv for it
        header = False

        if (os.path.isfile(fileName) == False):
            header = True

        output = open(fileName, 'a')

        if (header):
            output.write('Time, Total Bytes, Delta, On-Peak, Off-Peak\n')

        output.write('{0}, {1}, {2}, {3}, {4}\n'.format(timeKey, totalBytes, delta, peak, offPeak))
        output.close()

def getUserStats(deviceStatsArray, userMap):
    """ Go through the device dict array and add up all values
    that beint to each user
    """

    timeKey = int(time.time())

    userStatsArray = []

    # Create the default user
    unknownUser = {}
    unknownUser['Name'] = 'Unknown'
    unknownUser['Time'] = timeKey
    unknownUser['Total Bytes'] = 0
    unknownUser['Delta'] = 0
    unknownUser['On-Peak'] = 0
    unknownUser['Off-Peak'] = 0

    userStatsArray.append(unknownUser)

    # Open each device and determine to who it beints
    for deviceDict in deviceStatsArray:
        # Get Device info
        mac = deviceDict['MAC Address']
        ip = deviceDict['IP Address']

        # if (deviceDict['Time'] != timeKey):
        #     print('[INFO] Time key mismatch! (getUserStats)')

        # Use usermap to determine to who this mac beints
        if (mac in userMap):

            # Have we seen this user before?
            found = False
            for user in userStatsArray:
                # If we have seen before, add the values to existing values
                if (user['Name'] == userMap[mac]):
                    user['Total Bytes'] += deviceDict['Total Bytes']
                    user['Delta'] += deviceDict['Delta']
                    user['On-Peak'] += deviceDict['On-Peak']
                    user['Off-Peak'] += deviceDict['Off-Peak']
                    found = True

            # If we have not seen this user before, create the user and set the values
            if (found == False):
                tmpUser = {}
                tmpUser['Name'] = userMap[mac]
                tmpUser['Time'] = timeKey
                tmpUser['Total Bytes'] = deviceDict['Total Bytes']
                tmpUser['Delta'] = deviceDict['Delta']
                tmpUser['On-Peak'] = deviceDict['On-Peak']
                tmpUser['Off-Peak'] = deviceDict['Off-Peak']
                userStatsArray.append(tmpUser)

        # if the mac was not found the the userMap, add it to Unknown user
        else:
            userStatsArray[0]['Total Bytes'] += deviceDict['Total Bytes']
            userStatsArray[0]['Delta'] += deviceDict['Delta']
            userStatsArray[0]['On-Peak'] += deviceDict['On-Peak']
            userStatsArray[0]['Off-Peak'] += deviceDict['Off-Peak']

    return userStatsArray

def logUserStats(userStatsArray, userDir):
    """
    Append the user data to their csv files
    """

    if (not os.path.exists(userDir)):
        os.mkdir(userDir)

    for user in userStatsArray:
        fileName = userDir + '/' + user['Name'] + '.csv'
        header = False

        if (os.path.isfile(fileName) == False):
            header = True

        usercsv = open(fileName, 'a')

        if (header):
            usercsv.write('Time, Total Bytes, Delta, On-Peak, Off-Peak\n')

        usercsv.write('{0}, {1}, {2}, {3}, {4}\n'.format(user['Time'], user['Total Bytes'], user['Delta'], user['On-Peak'], user['Off-Peak']))
        usercsv.close()

def getTotalStats(userStats):
    """
    Loop through all user dicts and add their last value to total
    """

    timeKey = int(time.time())

    total = {}
    total['Time'] = timeKey
    total['Total Bytes'] = 0
    total['Delta'] = 0
    total['On-Peak'] = 0
    total['Off-Peak'] = 0

    for userDict in userStats:

        # if (userDict['Time'] != timeKey):
        #     print('[WARN] Time key mismatch! (getTotalStats)')

        total['Total Bytes'] += userDict['Total Bytes']
        total['Delta'] += userDict['Delta']
        total['On-Peak'] += userDict['On-Peak']
        total['Off-Peak'] += userDict['Off-Peak']

    return total

def logTotalStats(totalStats, totalFile):
    """
    Append the total to their csv files
    """

    if (not os.path.exists(os.path.dirname(totalFile))):
        os.mkdir(os.path.dirname(totalFile))

    header = False

    if (os.path.isfile(totalFile) == False):
        header = True

    totalcsv = open(totalFile, 'a')
    if (header):
        totalcsv.write('Time, Total Bytes, Delta, On-Peak, Off-Peak\n')

    totalcsv.write('{0}, {1}, {2}, {3}, {4}\n'.format(totalStats['Time'], totalStats['Total Bytes'], totalStats['Delta'], totalStats['On-Peak'], totalStats['Off-Peak']))
    totalcsv.close()

def getIpFromFileName(name):
    result = name.split('_')
    result = str(result[1])[:-4]

    return result

def getMacFromFileName(name):
    result = name.split('_')
    result = result[0].replace('-', ':')

    return result

def initSession(username, password):
    session = requests.session()

    raw = username + ':' + password
    encoded = base64.b64encode(raw.encode('utf-8'))

    auth = 'Basic ' + encoded.decode('utf-8')
    cookie = 'Authorization=' + auth

    session.headers = {
        'Host': '192.168.1.1',
        'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:46.0) Gecko/20100101 Firefox/46.0',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Content-Type': 'text/plain',
        'Cookie': cookie,
        'Referer': 'http://192.168.1.1/',
        'Connection': 'keep-alive'
    }

    return session

def decStrToIpStr(dec):
    binStr = bin(int(dec))

    binStr = binStr[2:]
    finalStr = ''

    """
    0: 0, 8 (8*0), ()
    1: 8, 16 (8*1)
    2: 16, 24 (8*2)
    3: 24, 32 (8*3)
    """

    for i in range(0, 4):
        tmp = binStr[8 * i : 8 * (i + 1)]
        tmp = int(tmp, 2)
        finalStr += str(tmp) + '.'

    return finalStr[:-1]

def loadUserMap(userMapFile):
    """
    MAC, User
    """
    userMap = {}

    if (os.path.isfile(userMapFile) == False):
        return userMap

    userMapFile = open(userMapFile)
    reader = csv.reader(userMapFile, delimiter=',', skipinitialspace=True)

    for row in reader:
        if (reader.line_num != 1):
            userMap[row[1]] = row[0]

    userMapFile.close()

    return userMap

def logout(session):
    # Configure page specific headers
    url = 'http://192.168.1.1/cgi?8'
    session.headers.update({'Referer': 'http://192.168.1.1/MenuRpm.htm'})
    data ='[/cgi/logout#0,0,0,0,0,0#0,0,0,0,0,0]0,0\r\n'

    try:
        r = session.post(url=url, data=data)
    except KeyboardInterrupt:
        #print('[ERROR] KeyboardInterrupt during getDeviceRecords()')
        raise
    except:
        print(str(datetime.datetime.now()) + ' [ERROR] Unexpected error: ', sys.exc_info()[0])
        return


    if (r.text != '[cgi]0\n[error]0'):
        print('[ERROR] Logout failed:')
        if (r.text == '<html><head><title>500 Internal Server Error</title></head><body><center><h1>500 Internal Server Error</h1></center></body></html>'):
            print('\t Another admin has logged in!')
        else:
            print('\t' + r.text)

main()
