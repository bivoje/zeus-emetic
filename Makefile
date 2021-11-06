SHELL := /bin/bash # for read -s option

install_path = /usr/bin/emetic
cronjob = '0 10 * * * sleep $${RANDOM:0:2}m; emetic update\n0 20 * * * sleep $${RANDOM:0:2}m; emetic update'

setup: config crontab

crontab: install
	@#echo 'a\n0 10 * * * sleep $${RANDOM:0:2}m; emetic update\n0 20 * * * sleep $${RANDOM:0:2}m; emetic update\n.\nwq\n' | cat #EDITOR=ed crontab -e
	@# $$ in bash is process number which would be unique when it is run
	echo -e "`crontab -l | grep -v emetic`""\n"$(cronjob) > /tmp/$$$$;\
	crontab /tmp/$$$$;\
	rm /tmp/$$$$
	@echo "crontab job installed"

config: install
	@read -p "username: " uid;\
	read -s -p "password: " pw;\
	echo '{"username":"'$$uid'","b64_password":"'"`echo -n $$pw | base64`"'"}' > `$(install_path) config ""`
	@echo `$(install_path) config ""` is created

install: prepare
	@if ! [ -e $(install_path) ]; then\
		sudo cp main.py $(install_path);\
		echo "installed in `which emetic`";\
	fi

prepare:
	sudo apt install bash cron python3

reset: uninstall
	@# $$ in bash is process number which would be unique when it is run
	crontab -l | grep -v emetic > /tmp/$$$$;\
	crontab /tmp/$$$$;\
	rm /tmp/$$$$
	@# FIXME doest not clean dependencies

uninstall:
	rm -f `emetic config ""` # FIXME does not clean cookie path?
	sudo rm -f $(install_path)
