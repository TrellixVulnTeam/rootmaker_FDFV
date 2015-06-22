#!/usr/bin/env python3

import os
import tempfile
import stat
import chroot
import packer
import shutil
import abc
import subprocess
import scheme

class File:
	def __init__(self, path, previous):
		self.path = path
		self.previous = previous
		self._mode = None

	def __str__(self):
		return self.path

	def up(self):
		return self.previous

	@property
	def mode(self):
		if(self._mode != None):
			return self._mode
		elif(self.previous != None):
			return self.previous.mode
		else:
			return 0o600	

	def current_mode(self, value):
		self._mode = value

		return self

	def chmod(self, mode, recursive = False):
		command = 'chmod '
		if recursive:
			command += '-Rf '
		command += oct(mode)[2:] + ' ' + self.path
		subprocess.check_output(command.split())
		# os.chmod(self.path, mode)
		return self

	def size(self):
		return int(subprocess.check_output(['du', '-shb', self.path]).split()[0].decode('utf-8'))

	@abc.abstractmethod
	def create(self, mode = None): pass

	@staticmethod
	def discover(path, previous):
		statInfo = os.lstat(path)
		if(stat.S_ISDIR(statInfo.st_mode)):
			return Directory(path, previous)
		elif(stat.S_ISREG(statInfo.st_mode)):
			return SimpleFile(path, previous)
		elif(stat.S_ISLNK(statInfo.st_mode)):
			try:
				return SymlinkFile(path, os.path.realpath(path), previous)
			except:
				return SymlinkFile(path, None, previous)
		elif(stat.S_ISBLK(statInfo.st_mode)):
			# TODO : Get major/minor
			return BlockDeviceFile(path, 0, 0, previous)
		elif(stat.S_ISCHR(statInfo.st_mode)):
			# TODO : Get major/minor
			return CharDeviceFile(path, 0, 0, previous)
		elif(stat.S_ISFIFO(statInfo.st_mode)):
			return FIFOFile(path, previous)
		elif(stat.S_ISSOCK(statInfo.st_mode)):
			return SocketFile(path, previous)
		else:
			raise RuntimeError('File %s : Type unknown' % path)


class DeviceFile(File):

	def __init__(self, path, type, major, minor, previous):
		self.type = stat.S_IFBLK
		self.major = major
		self.minor = minor
		File.__init__(self, path, previous)

	def create(self, mode = None):
		device = os.makedev(self.major, self.minor)
		if(mode != None):
			os.mknod(self.path, self.type|mode, device)
		else:
			os.mknod(self.path, self.type|self.mode, device)
		return self


class BlockDeviceFile(DeviceFile):
	def __init__(self, path, major, minor, previous):
		DeviceFile.__init__(self, path, stat.S_IFBLK, major, minor, previous)

class CharDeviceFile(DeviceFile):
	def __init__(self, path, major, minor, previous):
		DeviceFile.__init__(self, path, stat.S_IFCHR, major, minor, previous)

class FIFOFile(File): pass

class SocketFile(File): pass

class SimpleFile(File):

	def create(self, mode = None):
		with open(self.path, 'w'):
			pass
		if(mode != None):
			return self.chmod(mode)
		else:
			return self.chmod(self.mode)

	def write(self, data):
		file = os.open(self.path, os.O_CREAT|os.O_WRONLY)
		os.write(file, bytes(data, 'UTF-8'))
		os.close(file)
		return self

class SymlinkFile(File):

	def __init__(self, path, target, previous):
		self.target = target
		File.__init__(self, path, previous)

class Directory(File):

	def create(self, mode = None):
		if(mode != None): 
			os.makedirs(self.path, mode, True)
		else:
			os.makedirs(self.path, self.mode, True)
		return self
	
	def copytree(self, path):
		shutil.copytree(path, self.path)
		return self

	def listdir(self):
		result = []
		for i in os.listdir(self.path):
			absfilename = self.path + '/' + i
			try:
				result.append(File.discover(absfilename, self))
			except Exception as e:
				print("Error while listing dir : %s (%s)" % (absfilename, e))
		return result

	def export(self, path):
		# Weird behavior with device file
		# print("Export %s to %s" % (self.path, path))
		# shutil.copytree(self.path, path)
		subprocess.check_output(['cp', '-rf', self.path, path])
		return self

	def copy(self, path, enter = False, name = None, mode = None):
		if name == None:
			filename = os.path.basename(path)
		else:
			filename = name

		parts = path.split('://')
		if(len(parts) > 1):
			fileScheme = parts[0]
		else:
			fileScheme = 'file'

		finalPath = self.path + '/' + filename

		scheme.factory(fileScheme).copy(path, finalPath)
		file = File.discover(finalPath, self)

		if(mode != None):
			file.chmod(mode)
		else:
			file.chmod(self.mode)
		
		if(enter):
			return file
		else:
			return self

	def in_copy(self, path, name = None, mode = None):
		return self.copy(path, enter = True, name = name, mode = mode)

	def pack(self, format, fileobj):
		packer.factory(format).pack(self.path, fileobj)
		return self

	def unpack(self, format, fileobj):
		packer.factory(format).unpack(self.path, fileobj)
		return self

	def dir(self, path, enter = False, create = True, mode = None):
		dir = Directory(self.path + '/' + path, self)
		if create:
			dir.create()

		if(mode != None):
			dir.chmod(mode)
		else:
			dir.chmod(self.mode)

		if(enter):
			return dir
		else:
			return self

	def in_dir(self, path, create = True):
		return self.dir(path, enter = True, create = create)

	def file(self, name, enter = False, create = True, mode = None):
		file = SimpleFile(self.path + '/' + name, self)
		if create:
			file.create()

		if(mode != None):
			file.chmod(mode)
		else:
			file.chmod(self.mode)

		if(enter):
			return file
		else: 
			return self

	def in_file(self, name, create = True):
		return self.file(name, enter = True, create = create)

	def block_device_file(self, name, major, minor, enter = False, create = True, mode = None):
		file = BlockDeviceFile(self.path + '/' + name, major, minor, self)
		if create:
			file.create()

		if(mode != None):
			file.chmod(mode)
		else:
			file.chmod(self.mode)
		
		if(enter):
			return file
		else:
			return self

	def in_block_device_file(self, name, major, minor, create = True):
		return self.block_device_file(name, major, minor, enter = True, create = create)

	def char_device_file(self, name, major, minor, enter = False, create = True, mode = None):
		file = CharDeviceFile(self.path + '/' + name, major, minor, self)
		if create:
			file.create()

		if(mode != None):
			file.chmod(mode)
		else:
			file.chmod(self.mode)

		if(enter):
			return file
		else:
			return self

	def in_char_device_file(self, name, major, minor, create = True):
		return self.char_device_file(name, major, minor, enter = True, create = create)

class RootMaker:

	def __init__(self):
		self.rootfs = tempfile.TemporaryDirectory()

	# Manipulate files
	def root(self):
		return Directory(self.rootfs.name, None)
		
	# Execute commands
	def chroot(self, command):
		with chroot.ChrootEnvironment(self.rootfs) as env:
			def callback():
				return subprocess.call(command, shell=False)
			return env.call(callback)
	
