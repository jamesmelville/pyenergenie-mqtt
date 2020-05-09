# Based upon:
# - https://github.com/jeremypoulter/pyenergenie/blob/master/src/switch.py
# - https://github.com/whaleygeek/pyenergenie/blob/master/src/mihome_energy_monitor.py
import sys
import time
sys.path.insert(1, './pyenergenie/src')
import energenie as energenie
import energenie.Devices as energenieDevices
import paho.mqtt.client as mqtt
import Queue
import threading

# TODO: Make logging less verbose, or configurably verbose
# TODO: Log errors to separate output, so they can more easily be discovered
# TODO: Configure last_will on energenie_tx_mqtt so that we know when it has disappeared
# TODO: Move configuration into configuration file

mqtt_hostname = "localhost"
mqtt_port = 1883
mqtt_keepalive = 10
mqtt_username = ""
mqtt_password = ""
mqtt_client_id = "agn-sensor01-lon_energenie"
mqtt_subscribe_client_id = "agn-sensor01-lon_pyenergenie_subscribe"
mqtt_clean_session = True
mqtt_publish_topic = "emon"
mqtt_subscribe_topic = "energenie"

# TODO: Figure out how not to have these copied from the other file
MFRID_ENERGENIE                  = 0x04
PRODUCTID_MIHO004                = 0x01   #         Monitor only
PRODUCTID_MIHO005                = 0x02   #         Adaptor Plus
PRODUCTID_MIHO006                = 0x05   #         House Monitor
PRODUCTID_MIHO032                 = 0x0C  # FSK motion sensor
PRODUCTID_MIHO033                 = 0x0D    # FSK open sensor

q_rx_mqtt = Queue.Queue()
q_rx_energenie = Queue.Queue()
q_tx_mqtt = Queue.Queue()
q_tx_energenie = Queue.Queue()

rx_mqtt_client_connected = False
wait_for_energenie_tx = False
receive_paused_for_energenie_tx = False

# The callback for when the client receives a CONNACK response from the server.
def rx_mqtt_on_connect(client, userdata, flags, rc):
	global mqtt_subscribe_topic
	global rx_mqtt_client_connected

	print("rx_mqtt: Connected to %s:%s with result code %s" % (client._host, client._port, rc))
	rx_mqtt_client_connected = True
	print("rx_mqtt: Set rx_mqtt_client_connected as True = " + str(rx_mqtt_client_connected))

	# Subscribing in on_connect() means that if we lose the connection and
	# reconnect then subscriptions will be renewed.
	print("rx_mqtt: Subscribing to " + mqtt_subscribe_topic + "/#")
	client.subscribe(mqtt_subscribe_topic + "/#")

def rx_mqtt_on_disconnect(client, userdata, flags, rc):
	global rx_mqtt_client_connected
	rx_mqtt_client_connected = False
	print("rx_mqtt: Disconnected with result code " + str(rc))
	print("rx_mqtt: Stopping mqtt subscribe client loop...")
	client.loop_stop()

def rx_mqtt_on_subscribe(client, userdata, mid, granted_qos):
	print("rx_mqtt_on_subscribe: Subcribed for receiving mqtt - " + str(mid) + " with QoS="+str(granted_qos))

# The callback for when a PUBLISH message is received from the server.
def rx_mqtt_on_message(client, userdata, msg):
	global q_rx_mqtt
	q_rx_mqtt.put(msg)



def rx_mqtt():
	global mqtt_hostname
	global mqtt_port
	global mqtt_keepalive
	global mqtt_username
	global mqtt_password
	global mqtt_subscribe_client_id
	global mqtt_clean_session
	global mqtt_subscribe_topic
	global q_rx_mqtt
	global rx_mqtt_client_connected

	print("rx_mqtt: Starting mqtt subscribing loop...")
	while True:
		try:
			fromMqtt = mqtt.Client(client_id=mqtt_subscribe_client_id, clean_session=mqtt_clean_session)
			fromMqtt.on_connect = rx_mqtt_on_connect
			fromMqtt.on_disconnect = rx_mqtt_on_disconnect
			fromMqtt.on_subscribe = rx_mqtt_on_subscribe
			fromMqtt.on_message = rx_mqtt_on_message

			if mqtt_username != "":
				fromMqtt.username_pw_set(mqtt_username, mqtt_password)
			
			print("rx_mqtt: Connecting after this...")
			fromMqtt.connect(mqtt_hostname, mqtt_port, mqtt_keepalive)

			# Blocking call that processes network traffic, dispatches callbacks and
			# handles reconnecting.
			# Other loop*() functions are available that give a threaded interface and a
			# manual interface.
			print("rx_mqtt: Looping forever after this...")
			fromMqtt.loop_forever()
		except Exception as e:
			print("rx_mqtt: exception occurred")
			print(e)
		finally:
			print("rx_mqtt: Restarting...")


def mqtt_tx_energenie():
	global q_rx_mqtt

	while True:
		try:
			msg = q_rx_mqtt.get()
			print("mqtt_tx_energenie: " + msg.topic + " " + str(msg.payload))

			name = msg.topic.split("/", 2)[1]
			device = energenie.registry.get(name)
			if str(msg.payload) == "1":
				print("mqtt_tx_energenie: " + name + " - on")
				for x in range(0, 5):
					device.turn_on()
					print("mqtt_tx_energenie: " + name + " - on attempt " + str(x))
					time.sleep(0.1)
			else:
				print("mqtt_tx_energenie: " + name + " - off")
				for x in range(0, 5):
					device.turn_off()
					print("mqtt_tx_energenie: " + name + " - off attempt " + str(x))
					time.sleep(0.1)
		except Exception as e:
			print("mqtt_tx_energenie: Exception occurred")
			print(e)
		finally:
			q_rx_mqtt.task_done()
			


def rx_energenie(address, message):
	global q_rx_energenie

	#print("rx_energenie: new message from " + str(address) )

	if address[0] == MFRID_ENERGENIE:
		# Retrieve list of names from the registry, so we can refer to the name of the device
		for devicename in energenie.registry.names():
			#print("rx_energenie: checking if message from " + devicename)

			# Using the name, retrieve the device
			d = energenie.registry.get(devicename)

			# Check if the message is from the current device of this iteration
			if address[2] == d.get_device_id():
				# Yes we found the device, so add to processing queue
				#print("rx_energenie: Queuing message from " + str(address) + " - " + devicename)
				newQueueEntry = {'DeviceName': devicename, 'DeviceType': address[1]}
				q_rx_energenie.put(newQueueEntry)
				# The device was found, so break from the for loop
				break
	else:
		print("rx_energenie: Not an energenie device " + str(address))



def rx_energenie_process():
	global q_rx_energenie

	while True:
		try:
			#print("rx_energenie_process: awaiting item in q_rx_energenie...")
			refreshed_device = q_rx_energenie.get()
			d = energenie.registry.get( refreshed_device['DeviceName'] )

			#print("rx_energenie_process: processing message from " + refreshed_device['DeviceName'] + " (type: " + str(refreshed_device['DeviceType']) + ")...")
			#if refreshed_device['DeviceType'] == PRODUCTID_MIHO006:
			#	try:
			#		p = d.get_apparent_power()
			#		print("Power MIHO006: %s" % str(p))
			#		item = {'DeviceName': refreshed_device['DeviceName'], 'data': {"apparent_power": str(p)}}
			#		q_tx_mqtt.put(item)
			#	except Exception as e:
			#		print("rx_energenie_process: Exception getting power")
			#		print(e)
			#elif refreshed_device['DeviceType'] == PRODUCTID_MIHO005:
			#	try:
			#		p = d.get_reactive_power()
			#		v = d.get_voltage()
			#		print("Power MIHO005: %s" % str(p))
			#		item = {'DeviceName': refreshed_device['DeviceName'], 'data': {"reactive_power": str(p), 'voltage': v}}
			#		q_tx_mqtt.put(item)
			#	except Exception as e:
			#		print("rx_energenie_process: Exception getting power ")
			#		print(e)
			#else:
			#	print("rx_energenie_process: NOPE; No process defined for " + refreshed_device['DeviceName'] + " of type " + str(refreshed_device['DeviceType']))

			item = {'DeviceName': refreshed_device['DeviceName'], 'DeviceType': refreshed_device['DeviceType'], 'data': {}}
			for metric_name in dir(d.readings):
				if not metric_name.startswith("__"):
					value = getattr(d.readings, metric_name)
					item['data'][metric_name] = value
			q_tx_mqtt.put(item)

			q_rx_energenie.task_done()
		except Exception as e:
			print("rx_energenie_process: exception occurred")
			print(e)


			
def energenie_tx_mqtt():
	global mqtt_hostname
	global mqtt_port
	global mqtt_keepalive
	global mqtt_username
	global mqtt_password
	global mqtt_client_id
	global mqtt_clean_session
	global mqtt_publish_topic
	global q_tx_mqtt

	energenie_tx_mqtt_client_connected = False

	def energenie_tx_mqtt_on_connect(client, userdata, flags, rc):
		global energenie_tx_mqtt_client_connected
		if rc == 0:
			#print("energenie_tx_mqtt: client connected")
			client.is_connected = True
			energenie_tx_mqtt_client_connected = True
		else:
			print("energenie_tx_mqtt: Bad connection; rc = "+str(rc))
	
	def energenie_tx_mqtt_on_disconnect(client, userdata, rc):
		global energenie_tx_mqtt_client_connected
		#print("energenie_tx_mqtt: client disconnected " + str(rc))
		client.is_connected = False
		energenie_tx_mqtt_client_connected = False
		#client.loop_stop()
	
	def energenie_tx_mqtt_on_publish(client, userdata, mid):
		#print("energenie_tx_mqtt: publish of " + str(mid) + " successful")
		pass

	#TODO: Move client instantiation outside of loop, manage connection status with single object
	while True:
		print("energenie_tx_mqtt: creating mqtt.client...")
		toMqtt = mqtt.Client(client_id=mqtt_client_id, clean_session=mqtt_clean_session)
		toMqtt.is_connected = False
		toMqtt.on_connect = energenie_tx_mqtt_on_connect
		toMqtt.on_disconnect = energenie_tx_mqtt_on_disconnect
		toMqtt.on_publish = energenie_tx_mqtt_on_publish

		if mqtt_username <> "":
			print("energenie_tx_mqtt: using username and password...")
			toMqtt.username_pw_set(mqtt_username, mqtt_password)
		print("energenie_tx_mqtt: connecting to mqtt broker...")
		toMqtt.connect(mqtt_hostname, mqtt_port, mqtt_keepalive)
		print("energenie_tx_mqtt: toMqtt.loop_start() thread starting...")
		toMqtt.loop_start()

		#while not toMqtt.is_connected:
		#	print("energenie_tx_mqtt: waiting to ensure connection...")
		#	time.sleep(0.5)
		
		while True:
			try:
				#print("energenie_tx_mqtt: awaiting item in q_tx_mqtt...")
				item = q_tx_mqtt.get()

				#print("energenie_tx_mqtt: publishing item for " + item['DeviceName'] + " (" + str(item['DeviceType']) + ") found on queue...")
				#print(str(item))

				data = item['data']

				for metric in data.keys():
					value = data[metric]
					if value == True and type(value) == type(True):
						value = 1
					elif data[metric] == None:
						value = ""

					publish_topic = mqtt_publish_topic + "/" + item['DeviceName'] + "/" + metric
					#print("energenie_tx_mqtt: publishing '" + str( value ) + "' to topic " + publish_topic)
					publish_result = toMqtt.publish(publish_topic, value)
					#print("energenie_tx_mqtt: publish returned " + str(publish_result[1]))
				q_tx_mqtt.task_done()
			except Exception as e:
				print("energenie_tx_mqtt: exception occurred")
				print(e)
				if not toMqtt.is_connected:
					print("energenie_tx_mqtt: mqtt client no longer connected, breaking processing loop")
					break
		print("energenie_tx_mqtt: toMqtt.is_connected == " + str(toMqtt.is_connected))
		print("energenie_tx_mqtt: toMqtt.loop_stop()")
		toMqtt.loop_stop()
		print("energenie_tx_mqtt: sleeping for 5 seconds before restarting thread")
		time.sleep(5)

			

def main():
	global mqtt_hostname
	global mqtt_port
	global mqtt_keepalive
	global mqtt_username
	global mqtt_password
	global mqtt_client_id
	global mqtt_clean_session
	
	# Bind event receiver for inbound energenie messages
	print("Binding fsk_router.when_incoming to rx_energenie...")
	energenie.fsk_router.when_incoming(rx_energenie)

	# Start thread for processing received inbound energenie, then sending to mqtt
	print("Starting rx_energenie_process thread...")
	thread_rxProcessor = threading.Thread(target=rx_energenie_process)
	thread_rxProcessor.daemon = True
	thread_rxProcessor.start()
	
	# Start thread for processing received inbound energenie, then sending to mqtt
	print("Starting energenie_tx_mqtt thread...")
	thread_rxProcessor = threading.Thread(target=energenie_tx_mqtt)
	thread_rxProcessor.daemon = True
	thread_rxProcessor.start()

	# Start thread for receiving inbound mqtt messages, which will queue them for the other thread
	print("Starting rxFromMqtt thread...")
	thread_rxProcessor = threading.Thread(target=rx_mqtt)
	thread_rxProcessor.daemon = True
	thread_rxProcessor.start()

	# Start thread for processing mqtt messages, and sending them on to the energenie device
	print("Starting txToEnergenie thread...")
	thread_txToEnergenie = threading.Thread(target=mqtt_tx_energenie)
	thread_txToEnergenie.daemon = True
	thread_txToEnergenie.start()

	print("These are devices in the registry...")
	names = energenie.registry.names()
	for name in names:
		print(name)
		device = energenie.registry.get(name)

	while True:
		energenie.loop()
		time.sleep(0.25)


if __name__ == "__main__":
	energenie.init()

	try:
		main()
	finally:
		energenie.finished()
