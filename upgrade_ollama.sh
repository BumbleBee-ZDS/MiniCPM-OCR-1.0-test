#!/usr/bin/env bash
# 将本机 Ollama 从 0.35.0 升级到 0.40.13（支持 MiniCPM-OCR 1.0 的 minicpm_ocr_1_0 投影器）
# 用法：sudo bash upgrade_ollama.sh
set -euo pipefail

SRC=/tmp/ollama-new
TARBALL=/tmp/ollama-linux-amd64.tar.zst
BACKUP=/tmp/ollama-backup-$(date +%Y%m%d-%H%M%S)

if [[ ${EUID} -ne 0 ]]; then
    echo "请用 sudo 运行：sudo bash $0" >&2
    exit 1
fi

if [[ ! -x ${SRC}/bin/ollama ]]; then
    echo "未找到解压好的新版本，先从 ${TARBALL} 解压..." >&2
    [[ -f ${TARBALL} ]] || { echo "缺少 ${TARBALL}" >&2; exit 1; }
    mkdir -p "${SRC}"
    tar --zstd -xf "${TARBALL}" -C "${SRC}"
fi

echo "==> 备份现有安装到 ${BACKUP}"
mkdir -p "${BACKUP}"
[[ -f /usr/local/bin/ollama ]] && cp -a /usr/local/bin/ollama "${BACKUP}/ollama"
[[ -d /usr/local/lib/ollama ]] && cp -a /usr/local/lib/ollama "${BACKUP}/lib-ollama"

echo "==> 安装 ollama 到 /usr/local"
install -m 755 "${SRC}/bin/ollama" /usr/local/bin/ollama
mkdir -p /usr/local/lib
rm -rf /usr/local/lib/ollama
cp -a "${SRC}/lib/ollama" /usr/local/lib/ollama

echo "==> 重启服务"
systemctl daemon-reload
systemctl restart ollama
sleep 3

systemctl is-active ollama
/usr/local/bin/ollama --version
echo "==> 完成，旧版本备份在 ${BACKUP}"
