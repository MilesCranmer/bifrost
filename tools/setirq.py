#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2017, The Bifrost Authors. All rights reserved.
# Copyright (c) 2017, NVIDIA CORPORATION. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# * Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the distribution.
# * Neither the name of The Bifrost Authors nor the names of its
#   contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS ``AS IS'' AND ANY
# EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
# OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
import sys
import getopt


def usage(exitCode=None):
	print """%s - Configure the IRQ bindings for a particular network interface

Usage: %s [OPTIONS] interface cpu0 [cpu1 [...]]

Options:
-h, --help             Display this help information
""" % (os.path.basname(__file__), os.path.basename(__file__))
	
	if exitCode is not None:
		sys.exit(exitCode)
	else:
		return True


def parseConfig(args):
	config = {}
	config['args'] = []
	
	# Read in and process the command line flags
	try:
		opts, arg = getopt.getopt(args, "h", ["help",])
	except getopt.GetoptError, err:
		# Print help information and exit:
		print str(err) # will print something like "option -a not recognized"
		usage(exitCode=2)
		
	# Work through opts
	for opt, value in opts:
		if opt in ('-h', '--help'):
			usage(exitCode=0)
		else:
			assert False
			
	# Add in arguments
	config['args'] = arg
	
	# Validate
	if len(config['args']) < 2:
		raise RuntimeError("Need to specify the device name and at least one CPU to bind to")
		
	# Return configuration
	return config


def compute_mask(cpu):
	"""
	Given a CPU number, return a bitmask that can be used in /proc/irq to set
	the processor affinity for an interrupt.
	"""
	
	return 1<<cpu


def write_irq_smp_affinity(irq, mask):
	"""
	Write the given process affinity mask to /proc/irq for the speicifed 
	interrupt.
	"""
	
	mask_str = "%08x" % mask
	filename = "/proc/irq/%i/smp_affinity" % irq
	with open(filename, 'w') as f:
		f.write(mask_str+"\n")


def main(args):
	config = parseConfig(args)
	interface = config['args'][0]
	cpus = [int(v,10) for v in config['args'][1:]]
	
	fh = open('/proc/interrupts', 'r')
	lines = fh.read()
	fh.close()
	
	irqs = {}
	for line in lines.split('\n'):
		if line.find(interface) != -1:
			fields = line.split()
			irq = int(fields[0][:-1], 10)
			procs = [int(v,10) for v in fields[1:-2]]
			type = fields[-2]
			name = fields[-1]
			
			mv = max(procs)
			mi = procs.index(mv)
			irqs[irq] = {'cpu':mi, 'type':type, 'name':name, 'count':mv}
			
	print "Interface: %s" % interface
	print "%4s  %16s  %16s  %7s  %7s" % ('IRQ', 'Name', 'Type', 'Old CPU', 'New CPU')  
	for i,irq in enumerate(sorted(irqs.keys())):
		oCPU = irqs[irq]['cpu']
		nCPU = cpus[i % len(cpus)]
		
		print "%4i  %16s  %16s  %7i  %7i" % (irq, irqs[irq]['name'], irqs[irq]['type'], oCPU, nCPU)
		
		mask = compute_mask(nCPU)
		write_irq_smp_affinity(irq, mask)


if __name__ == "__main__":
	main(sys.argv[1:])
	