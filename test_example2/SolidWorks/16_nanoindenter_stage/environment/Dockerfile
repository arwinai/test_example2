# SolidWorks cannot be installed, licensed, or driven headlessly in a
# Docker container: it requires a live GUI session on a Windows host with
# a purchased/activated SolidWorks license, driven through the COM API
# (pywin32's win32com.client.Dispatch("SldWorks.Application")).
#
# Harbor's Windows container support explicitly has no display forwarding
# or input simulation for GUI apps -- see:
# https://www.harborframework.com/docs/tasks/windows-container-support#command-execution
#
# This task is NOT runnable through `harbor run` in this repo checkout.
# NOTE also that this environment/ currently holds only input.png -- the
# starting Main.SLDASM (and its ~47 referenced part/sub-assembly files)
# has not been supplied yet; see solution/solve.sh.
#
# Run it locally on a Windows machine with SolidWorks installed instead:
#   1. Open environment/Main.SLDASM (the in-situ tension/compression test
#      stage, once supplied) and read instruction.md.
#   2. Add the low-profile removable belt guard, remove the side plate,
#      extend the fixture plate with M8 mounting holes, and replace the
#      40T GT2 pulley on the main shaft with a 60T GT2 pulley.
#   3. Save the top assembly, then run:
#      python tests/task/harness/harness.py <path-to-saved-assembly>
#
# TODO: FROM mcr.microsoft.com/windows/servercore:ltsc2022  -- or whatever
#       base the target Windows host's SolidWorks install actually needs
#       (SolidWorks has no supported Windows Server deployment story; a
#       real client OS image may be required instead of servercore).
# TODO: install SolidWorks itself (license required -- cannot be scripted
#       or verified from this environment).
# TODO: install Python + pywin32 so tests/task/harness/harness.py and
#       common/solidworks_session.py are runnable against the live COM
#       session.
