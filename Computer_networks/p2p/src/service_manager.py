#  This file is part of network emulation test model.
#
#  Copyright (C) 2010, 2011  Vladimir Rutsky <altsysrq@gmail.com>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

__author__  = "Vladimir Rutsky <altsysrq@gmail.com>"
__license__ = "GPL"

__all__ = ["Packet", "InvalidPacketException", "RouterServiceManager"]

"""Manager for services built on top of DatagramRouter.
"""

import Queue
import threading
import time
import logging
import struct
from collections import namedtuple

from recordtype import recordtype

import config
from datagram import datagram

class InvalidPacketException(Exception):
    pass

# TODO: Mess with `time'.
# TODO: `delivered_from' is additional not required information.
class Packet(recordtype('PacketBase', 'src dest data delivered_from time')):
    def __init__(self, *args, **kwargs):
        if len(args) < 5 and 'time' not in kwargs:
            kwargs['time'] = time.time()
        super(Packet, self).__init__(*args, **kwargs)

    def __eq__(self, other):
        return (
            self.src == other.src and
            self.dest == other.dest and
            self.data == other.data and
            self.delivered_from == other.delivered_from)

    def __ne__(self, other):
        return not self == other

    def __str__(self):
        return "Packet(src={src}, dest={dest}, "\
            "delivered_from={delivered_from}, time={time}, "\
            "data=0x{data})".format(
                src=self.src, dest=self.dest, data=self.data.encode('hex'),
                delivered_from=self.delivered_from,
                time=self.time)

def packet_to_datagram(packet, protocol):
    time_data = struct.pack("d", packet.time)
    return datagram(type=protocol, src=packet.src,
        dest=packet.dest,
        data=packet.data + time_data)

def datagram_to_packet(datagram, delivered_from):
    time_data_len = struct.calcsize("d")
    if len(datagram.data) < time_data_len:
        raise InvalidPacketException()

    time_ = struct.unpack("d", datagram.data[-time_data_len:])[0]

    return datagram.type, Packet(src=datagram.src, dest=datagram.dest,
        delivered_from=delivered_from,
        data=datagram.data[:-time_data_len], time=time_)

class RouterServiceManager(object):
    # `_receive_queue' and `_send_queue' are queues for received and send
    # Packet's accordingly.
    # TODO: rename to something like `ServiceTransmitter'.
    class ServiceInfo(
            recordtype('ServiceInfoBase', 'name receive_queue send_queue')):

        def send(self, packet):
            assert isinstance(packet, Packet)

            self.send_queue.put(packet)

        def receive(self, block=True):
            try:
                return self.receive_queue.get(block)
            except Queue.Empty:
                return None

        def send_data(self, dest, data):
            self.send(Packet(self.name, dest, data, self.name))

        def receive_data(self, block=True):
            packet = self.receive(block)
            if packet is not None:
                return (packet.src, packet.data)
            else:
                return None

    def __init__(self, datagram_router):
        super(RouterServiceManager, self).__init__()

        self._datagram_router = datagram_router

        self._logger = logging.getLogger(
            "RouterServiceManager.router={0}".format(
                self._datagram_router.name))

        # { protocol: ServiceInfo() }
        self._services = {}
        self._services_lock = threading.Lock()

        # If working thread will be able to acquire the lock, then it should
        # terminate himself.
        self._exit_lock = threading.RLock()
        self._exit_lock.acquire()

        self._working_thread = threading.Thread(target=self._work)
        self._working_thread.start()

    # TODO
    def terminate(self):
        # Release exit lock and wait until working thread will not terminate.
        self._exit_lock.release()
        self._working_thread.join()

    @property
    def name(self):
        return self._datagram_router.name

    def _register_service_info(self, protocol, service_info):
        self._logger.info("Registering service {0}".format(protocol))

        with self._services_lock:
            assert protocol not in self._services
            self._services[protocol] = service_info

    def register_service(self, protocol):
        service_info = \
            RouterServiceManager.ServiceInfo(
                self.name, Queue.Queue(), Queue.Queue())
        self._register_service_info(protocol, service_info)

        return service_info

    def _work(self):
        def deliver_to_network():
            with self._services_lock:
                services = self._services.items()[:]

            for i in xrange(100):
                sent_data = False
                
                for protocol, service_info in services:
                    try:
                        packet = service_info.send_queue.get(False)
                    except Queue.Empty:
                        continue
                    datagram = packet_to_datagram(packet, protocol)

                    self._logger.debug(
                        "Client to network (protocol={0}):\n"
                        "  {1}".format(
                            protocol, packet))

                    self._datagram_router.send(datagram)

                    sent_data = True

                if not sent_data:
                    break

        def deliver_from_network():
            while True:
                delivered_from, datagram = \
                    self._datagram_router.receive(block=False)
                if datagram is None:
                    break
                else:
                    protocol, packet = datagram_to_packet(
                        datagram, delivered_from)
                    
                    with self._services_lock:
                        if protocol in self._services:
                            self._logger.debug(
                                "Network to client (protocol={0}):\n"
                                "  {1}\n  {2}".format(
                                    protocol, datagram, packet))
                            
                            packet.time = time.time() - packet.time

                            self._services[protocol].receive_queue.put(packet)
                        else:
                            self._logger.warning(
                                "Packet for unregistered service {0} "
                                "unhandled:\n  {1}".format(
                                    protocol, packet))

        self._logger.info("Working thread started")

        while True:
            if self._exit_lock.acquire(False):
                # Obtained exit lock. Terminate.

                self._exit_lock.release()
                self._logger.info("Exit working thread")
                return

            deliver_to_network()
            deliver_from_network()

            time.sleep(config.thread_sleep_time)

def _test(level=None):
    # TODO: Use in separate file to test importing functionality.

    from testing import unittest, do_tests
    
    from duplex_link import FullDuplexLink, LossFunc
    from frame import SimpleFrameTransmitter
    from sliding_window import FrameTransmitter
    from link_manager import RouterLinkManager
    from routing_table import loopback_routing_table, LocalRoutingTable
    from datagram import DatagramRouter

    class Tests(object):
        class TestPacket(unittest.TestCase):
            def test_main(self):
                t = time.time()
                p1 = Packet(    1,      2,      "3", 4, t)
                p2 = Packet(src=1, dest=2, data="3", delivered_from=4, time=t)
                self.assertEqual(p1, p2)
                self.assertEqual(p1.src,  1)
                self.assertEqual(p1.dest, 2)
                self.assertEqual(p1.data, "3")
                self.assertEqual(p1.time, t)

                d1 = packet_to_datagram(p1, 30)
                self.assertEqual(d1,
                    datagram(30, p1.src, p1.dest, p1.data +
                        struct.pack("d", t)))

                d1_type, p1_ = datagram_to_packet(d1, 4)
                self.assertEqual(d1_type, d1.type)
                self.assertEqual(p1_, p1)
                self.assertEqual(p1_.time, p1.time)

        class Test_ServiceInfo(unittest.TestCase):
            def test_main(self):
                sm = RouterServiceManager.ServiceInfo(0, 1, 2)
                self.assertEqual(sm.name, 0)
                self.assertEqual(sm.receive_queue, 1)
                self.assertEqual(sm.send_queue, 2)

        class TestRouterServiceManagerBasic(unittest.TestCase):
            def setUp(self):
                self.lm1 = RouterLinkManager()

                self.dt1 = DatagramRouter(
                    router_name=1,
                    link_manager=self.lm1)

            def test_constructor(self):
                sm = RouterServiceManager(self.dt1)

                sm.terminate()

            def test_main(self):
                sm = RouterServiceManager(self.dt1)

                s10 = sm.register_service(10)

                sm.terminate()
                
            def tearDown(self):
                self.dt1.terminate()

        class TestRouterServiceManager1(unittest.TestCase):
            def setUp(self):
                self.lm1 = RouterLinkManager()

                self.dt1 = DatagramRouter(
                    router_name=1,
                    link_manager=self.lm1)

                self.sm1 = RouterServiceManager(self.dt1)

            def test_send_receive_data(self):
                self.s30 = self.sm1.register_service(30)

                text = "Some text text."
                self.s30.send_data(1, text)
                self.assertEqual(self.s30.receive_data(), (1, text))
                self.assertEqual(self.s30.receive_data(False), None)

            def test_main(self):
                s10 = self.sm1.register_service(10)

                s15 = self.sm1.register_service(15)

                unreach_p10 = Packet(1, 2, "unreachable test (10)", 1)
                s10.send(unreach_p10)

                p10_1 = Packet(1, 1, "test (10)", 1)
                s10.send(p10_1)

                self.assertEqual(s10.receive(), p10_1)

                self.assertEqual(s10.receive(block=False), None)

                p15_1 = Packet(1, 1, "test (15)", 1)
                p10_2 = Packet(1, 1, "test 2 (10)", 1)

                s10.send(p10_1)
                s15.send(p15_1)
                s10.send(p10_2)

                self.assertEqual(s15.receive(), p15_1)
                self.assertEqual(s15.receive(block=False), None)
                self.assertEqual(s10.receive(), p10_1)
                self.assertEqual(s10.receive(), p10_2)
                self.assertEqual(s10.receive(block=False), None)

                text = "".join(map(chr, xrange(256)))
                p15_2 = Packet(1, 1, text * 10, 1)
                s15.send(p15_2)
                s10.send(p10_1)
                self.assertEqual(s10.receive(), p10_1)
                self.assertEqual(s15.receive(), p15_2)

            def tearDown(self):
                self.sm1.terminate()
                self.dt1.terminate()

        class TestRouterServiceManager2(unittest.TestCase):
            def setUp(self):
                l1, l2 = FullDuplexLink()

                sft1 = SimpleFrameTransmitter(node=l1)
                sft2 = SimpleFrameTransmitter(node=l2)

                self.ft1 = FrameTransmitter(simple_frame_transmitter=sft1,
                    debug_src=1, debug_dest=2)
                self.ft2 = FrameTransmitter(simple_frame_transmitter=sft2,
                    debug_src=2, debug_dest=1)

                rlm1 = RouterLinkManager()
                rlm2 = RouterLinkManager()

                self.dr1 = DatagramRouter(
                    router_name=1,
                    link_manager=rlm1,
                    routing_table=LocalRoutingTable(1, rlm1))
                self.dr2 = DatagramRouter(
                    router_name=2,
                    link_manager=rlm2,
                    routing_table=LocalRoutingTable(2, rlm2))

                rlm1.add_link(2, self.ft1)
                rlm2.add_link(1, self.ft2)

                self.sm1 = RouterServiceManager(self.dr1)
                self.sm2 = RouterServiceManager(self.dr2)

                self.s1_100 = self.sm1.register_service(100)
                self.s2_100 = self.sm2.register_service(100)

            def _test_transmit(self):
                s1_77 = self.sm1.register_service(77)
                s2_77 = self.sm2.register_service(77)

                d12 = Packet(1, 2, "test")
                s1_77.send(d12)
                self.assertEqual(s2_77.receive(), d12)
                s2_77.send(d12)
                self.assertEqual(s2_77.receive(), d12)

                s1_33 = self.sm1.register_service(33)
                s2_33 = self.sm2.register_service(33)

                d21 = Packet(2, 1, "test 2")
                s2_33.send(d21)
                self.assertEqual(s1_33.receive(), d21)
                s1_33.send(d21)
                self.assertEqual(s1_33.receive(), d21)

                text = "".join(map(chr, xrange(256)))
                d_big = Packet(1, 2, text * 5)
                s1_33.send(d_big)
                self.assertEqual(s2_33.receive(), d_big)

                d12_2 = Packet(1, 2, "test 2")
                d12_3 = Packet(1, 2, "test 3")

                s1_33.send(d12)
                s1_33.send(d12_2)
                self.assertEqual(s2_33.receive(), d12)
                s1_77.send(d12_3)
                self.assertEqual(s2_77.receive(), d12_3)
                self.assertEqual(s2_33.receive(), d12_2)

            def test_time(self):
                data = "test"
                self.s1_100.send_data(2, data)
                p = self.s2_100.receive()
                self.assertEqual(p.data, data)
                # TODO: Assume computer is not slow.
                self.assertLess(p.time, 5.0)
                self.assertGreaterEqual(p.time, 0)

            def tearDown(self):
                self.sm1.terminate()
                self.sm2.terminate()

                self.dr1.terminate()
                self.dr2.terminate()

                self.ft1.terminate()
                self.ft2.terminate()

        class _TestRouterServiceManager2WithLosses(unittest.TestCase):
            def setUp(self):
                l1, l2 = FullDuplexLink(loss_func=LossFunc(0.001, 0.001, 0.001))

                sft1 = SimpleFrameTransmitter(node=l1)
                sft2 = SimpleFrameTransmitter(node=l2)

                self.ft1 = FrameTransmitter(simple_frame_transmitter=sft1,
                    debug_src=1, debug_dest=2)
                self.ft2 = FrameTransmitter(simple_frame_transmitter=sft2,
                    debug_src=2, debug_dest=1)

                rlm1 = RouterLinkManager()
                rlm2 = RouterLinkManager()

                self.dr1 = DatagramRouter(
                    router_name=1,
                    link_manager=rlm1,
                    routing_table=LocalRoutingTable(1, rlm1))
                self.dr2 = DatagramRouter(
                    router_name=2,
                    link_manager=rlm2,
                    routing_table=LocalRoutingTable(2, rlm2))

                rlm1.add_link(2, self.ft1)
                rlm2.add_link(1, self.ft2)

                self.sm1 = RouterServiceManager(self.dr1)
                self.sm2 = RouterServiceManager(self.dr2)

            def test_transmit(self):
                s1_77 = self.sm1.register_service(77)
                s2_77 = self.sm2.register_service(77)

                d12 = Packet(1, 2, "test")
                s1_77.send(d12)
                self.assertEqual(s2_77.receive(), d12)
                s2_77.send(d12)
                self.assertEqual(s2_77.receive(), d12)

                s1_33 = self.sm1.register_service(33)
                s2_33 = self.sm2.register_service(33)

                d21 = Packet(2, 1, "test 2")
                s2_33.send(d21)
                self.assertEqual(s1_33.receive(), d21)
                s1_33.send(d21)
                self.assertEqual(s1_33.receive(), d21)

                text = "".join(map(chr, xrange(256)))
                d_big = Packet(1, 2, text * 5)
                s1_33.send(d_big)
                self.assertEqual(s2_33.receive(), d_big)

                d12_2 = Packet(1, 2, "test 2")
                d12_3 = Packet(1, 2, "test 3")

                s1_33.send(d12)
                s1_33.send(d12_2)
                self.assertEqual(s2_33.receive(), d12)
                s1_77.send(d12_3)
                self.assertEqual(s2_77.receive(), d12_3)
                self.assertEqual(s2_33.receive(), d12_2)

            def tearDown(self):
                self.sm1.terminate()
                self.sm2.terminate()

                self.dr1.terminate()
                self.dr2.terminate()

                self.ft1.terminate()
                self.ft2.terminate()

    do_tests(Tests, level=level)

if __name__ == "__main__":
    _test(level=0)

# vim: set ts=4 sw=4 et:
