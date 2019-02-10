# Based upon:
# - https://github.com/jeremypoulter/pyenergenie/blob/master/src/switch.py
# - https://github.com/whaleygeek/pyenergenie/blob/master/src/mihome_energy_monitor.py
import sys
import time
sys.path.insert(0, '/shared/pyenergenie-master/src')
import energenie
import energenie.Devices
import paho.mqtt.client as mqtt
import Queue
import threading

mqtt_hostname = "localhost"
mqtt_port = 1883
mqtt_keepalive = 60
mqtt_username = ""
mqtt_password = ""
mqtt_client_id = "agn-sensor01-lon_energenie"
mqtt_clean_session = True
mqtt_publish_topic = "emon"
mqtt_subscribe_topic = "energenie"

# TODO: Figure out how not to have these copied from the other file
MFRID_ENERGENIE                  = 0x04
PRODUCTID_MIHO004                = 0x01   #         Monitor only
PRODUCTID_MIHO005                = 0x02   #         Adaptor Plus
PRODUCTID_MIHO006                = 0x05   #         House Monitor


q_rx_mqtt = Queue.Queue()
q_rx_energenie = Queue.Queue()
q_tx_mqtt = Queue.Queue()
#q_tx_energenie = Queue.Queue() # Not yet in use, TODO

def rx_mqtt():
	global mqtt_hostname
	global mqtt_port
	global mqtt_keepalive
	global mqtt_username
	global mqtt_password
	global mqtt_client_id
	global mqtt_clean_session
	global mqtt_subscribe_topic
	global q_rx_mqtt

	# The callback for when the client receives a CONNACK response from the server.
	def on_connect(client, userdata, flags, rc):
		global mqtt_subscribe_topic
		print("Connected with result code "+str(rc))

		# Subscribing in on_connect() means that if we lose the connection and
		# reconnect then subscriptions will be renewed.
		print("Subscribing to "+mqtt_subscribe_topic+"/#")
		client.subscribe(mqtt_subscribe_topic + "/#")

	# The callback for when a PUBLISH message is received from the server.
	def on_message(client, userdata, msg):
		global q_rx_mqtt
		q_rx_mqtt.put(msg)



	print("Starting mqtt subscribing loop...")
	while True:
		try:
			client = mqtt.Client(client_id=mqtt_client_id, clean_session=mqtt_clean_session)
			client.on_connect = on_connect
			client.on_message = on_message

			if mqtt_username != "":
				client.username_pw_set(mqtt_username, mqtt_password)
			client.connect(mqtt_hostname, mqtt_port, mqtt_keepalive)

			# Blocking call that processes network traffic, dispatches callbacks and
			# handles reconnecting.
			# Other loop*() functions are available that give a threaded interface and a
			# manual interface.
			client.loop_forever()
		finally:
			print("Restarting...")


def mqtt_tx_energenie():
	global q_rx_mqtt

	while True:
		try:
			msg = q_rx_mqtt.get()
			print(msg.topic+" "+str(msg.payload))
			name = msg.topic.split("/", 2)[1]
			device = energenie.registry.get(name)
			if str(msg.payload) == "1":
				print(name+" on")
				for x in range(0, 5):
					device.turn_on()
					time.sleep(0.1)
			else:
				print(name+" off")
				for x in range(0, 5):
					device.turn_off()
					time.sleep(0.1)
		except:
			print("Got exception")
		finally:
			q_rx_mqtt.task_done()
			


def rx_energenie(address, message):
	global q_rx_energenie

	print("rx_energenie: new message from " + str(address) )

	if address[0] == MFRID_ENERGENIE:
		# Retrieve list of names from the registry, so we can refer to the name of the device
		for devicename in energenie.registry.names():
			print("rx_energenie: checking if message from " + devicename)

			# Using the name, retrieve the device
			d = energenie.registry.get(devicename)

			# Check if the message is from the current device of this iteration
			if address[2] == d.get_device_id():
				# Yes we found the device, so add to processing queue
				print("rx_energenie: YES; add to process queue")
				newQueueEntry = {'DeviceName': devicename, 'DeviceType': address[1]}
				q_rx_energenie.put(newQueueEntry)
				# The device was found, so break from the for loop
				break
	else:
		print("Not an energenie device...?")



def rx_energenie_process():
	global q_rx_energenie

	while True:
		print("rx_energenie_process: awaiting item in q_rx_energenie...")
		refreshed_device = q_rx_energenie.get()
		d = energenie.registry.get( refreshed_device['DeviceName'] )

		print("rx_energenie_process: " + refreshed_device['DeviceName'] + " (type: " + str(refreshed_device['DeviceType']) + ") process beginning...")
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

		item = {'DeviceName': refreshed_device['DeviceName'], 'data': {}}
		for metric_name in dir(d.readings):
			if not metric_name.startswith("__"):
				value = getattr(d.readings, metric_name)
				item['data'][metric_name] = value
		q_tx_mqtt.put(item)

		q_rx_energenie.task_done()



			
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

	print("energenie_tx_mqtt: creating mqtt.client...")
	toMqtt = mqtt.Client(client_id=mqtt_client_id, clean_session=mqtt_clean_session)

	if mqtt_username <> "":
		print("energenie_tx_mqtt: using username and password...")
		toMqtt.username_pw_set(mqtt_username, mqtt_password)
	print("energenie_tx_mqtt: connecting to mqtt broker...")
	toMqtt.connect(mqtt_hostname, mqtt_port, mqtt_keepalive)
	
	while True:
		print("energenie_tx_mqtt: awaiting item in q_tx_mqtt...")
		item = q_tx_mqtt.get()
		print("energenie_tx_mqtt: item for " + item['DeviceName'] + " found on queue...")
		print(str(item))
		data = item['data']

		for metric in data.keys():
			value = data[metric]
			if value is True:
				value = 1

			publish_topic = mqtt_publish_topic + "/" + item['DeviceName'] + "/" + metric
			print("energenie_tx_mqtt: publishing " + str( value ) + " to topic " + publish_topic)
			toMqtt.publish(publish_topic, data[metric])
		q_tx_mqtt.task_done()

def main():
	global mqtt_hostname
	global mqtt_port
	global mqtt_keepalive
	global mqtt_username
	global mqtt_password
	global mqtt_client_id
	global mqtt_clean_session
	
	# Start thread for receiving inbound energenie messages
	#print("Starting rxFromEnergenie thread...")
	#thread_rxFromEnergenie = threading.Thread(target=rx_energenie)
	#thread_rxFromEnergenie.daemon = True
	#thread_rxFromEnergenie.start()
	print("Binding fsk_router.when_incoming to rx_energenie...")
	energenie.fsk_router.when_incoming(rx_energenie)

	print("Starting rx_energenie_process thread...")
	# Start thread for processing received inbound energenie, then sending to mqtt
	thread_rxProcessor = threading.Thread(target=rx_energenie_process)
	thread_rxProcessor.daemon = True
	thread_rxProcessor.start()
	
	print("Starting energenie_tx_mqtt thread...")
	# Start thread for processing received inbound energenie, then sending to mqtt
	thread_rxProcessor = threading.Thread(target=energenie_tx_mqtt)
	thread_rxProcessor.daemon = True
	thread_rxProcessor.start()

	#print("Starting rxFromMqtt thread...")
	#thread_rxProcessor = threading.Thread(target=rx_mqtt)
	#thread_rxProcessor.daemon = True
	#thread_rxProcessor.start()

	# Start a thread to process the key presses
	#thread_txToEnergenie = threading.Thread(target=mqtt_tx_energenie)
	#thread_txToEnergenie.daemon = True
	#thread_txToEnergenie.start()

	print("These are devices in the registry...")
	names = energenie.registry.names()
	for name in names:
		print(name)
		device = energenie.registry.get(name)

	while True:
		energenie.loop()
	

if __name__ == "__main__":
	energenie.init()

	try:
		main()
	finally:
		energenie.finished()