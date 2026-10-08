FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client rsync ca-certificates && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir 'ansible==2.9.27' PyYAML jinja2
WORKDIR /app/fleet-automation
COPY . /app/fleet-automation
RUN chmod +x bin/fleet-ansible
CMD ["bash"]
