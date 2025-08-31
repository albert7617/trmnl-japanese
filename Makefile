IMAGE_NAME=trmnl-japanese
CONTAINER_NAME=trmnl-japanese
PYTHON=py
COMPOSE_FILE ?= docker-compose.yml
ENV_FILE=.env

OPTIONS:=

ifeq ($(OS),Windows_NT)
VENV_SCRIPTS_ACTIVATE=venv\Scripts\activate
else
VENV_SCRIPTS_ACTIVATE=source env/bin/activate
endif

dockerbuild:
	docker build -t ${CONTAINER_NAME} .

dockerclean:
	-docker stop ${CONTAINER_NAME}
	-docker rm ${CONTAINER_NAME}

dockerrebuild: dockerclean dockerbuild

dockerrun: dockerclean
	docker run -d \
			--name ${CONTAINER_NAME} \
			--restart always \
			-v ${CURDIR}/data:/app/data \
			-p 8091:80 \
			${CONTAINER_NAME}

distclean:
	rm -rf venv

composebuild:
	docker-compose -f $(COMPOSE_FILE) build $(CONTAINER_NAME)

composeup:
	docker-compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) up -d

composedown:
	docker-compose -f $(COMPOSE_FILE) down

composeclean: composedown
	docker-compose -f $(COMPOSE_FILE) rm -fv
	docker volume prune -f

composerebuild: composeclean composebuild composeup

################################################

build: requirements.txt
	$(PYTHON) -m venv venv
	$(VENV_SCRIPTS_ACTIVATE); pip install -r requirements.txt
