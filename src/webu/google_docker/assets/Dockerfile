FROM python:3.11-slim

ARG APT_MIRROR=http://deb.debian.org/debian
ARG APT_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=pypi.org

ENV DEBIAN_FRONTEND=noninteractive

RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|http://deb.debian.org/debian|${APT_MIRROR}|g; s|http://security.debian.org/debian-security|${APT_SECURITY_MIRROR}|g; s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && if [ -f /etc/apt/sources.list ]; then \
        sed -i "s|http://deb.debian.org/debian|${APT_MIRROR}|g; s|http://security.debian.org/debian-security|${APT_SECURITY_MIRROR}|g; s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" /etc/apt/sources.list; \
    fi

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libdbus-1-3 \
        libdrm2 \
        libgbm1 \
        libglib2.0-0 \
        libgtk-3-0 \
        libnspr4 \
        libnss3 \
        libx11-6 \
        libx11-xcb1 \
        libxcb1 \
        libxcomposite1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxrandr2 \
        xdg-utils \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    WEBU_SERVICE_LOG=/tmp/webu-google-docker.log \
    WEBU_RUNTIME_ENV=docker \
    WEBU_SERVICE_MODE=google-docker \
    WEBU_GOOGLE_PROFILE_BOOTSTRAP_ARCHIVE=/home/user/app/bootstrap/google_api_profile.bin
WORKDIR /home/user/app

COPY --chown=user requirements.txt ./requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && if [ -s requirements.txt ]; then pip install --no-cache-dir -i ${PIP_INDEX_URL} --trusted-host ${PIP_TRUSTED_HOST} -r requirements.txt; fi \
    && python -m playwright install chromium

COPY --chown=user pyproject.toml LICENSE ./
COPY --chown=user src ./src
COPY --chown=user bootstrap ./bootstrap

RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} --trusted-host ${PIP_TRUSTED_HOST} --no-deps .

EXPOSE 18100 18200

CMD ["sh", "-lc", "if [ \"${WEBU_SERVICE_MODE}\" = \"hub\" ]; then python -m webu.google_hub.server --host 0.0.0.0 --port ${WEBU_HUB_PORT:-18100}; else python -m webu.google_docker serve --host 0.0.0.0 --port ${WEBU_DOCKER_PORT:-18200}; fi 2>&1 | tee -a ${WEBU_SERVICE_LOG}"]