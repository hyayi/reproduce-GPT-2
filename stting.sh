#!/bin/bash

# 설치 경로
INSTALL_DIR="/workspace/miniconda3"
SHELL_RC="$HOME/.bashrc"  # zsh 사용 시 .zshrc로 변경

echo "🧹 기존 Conda 제거 중..."
sudo rm -rf /opt/conda /root/miniconda3 /usr/local/miniconda3

echo "📦 Miniconda 다운로드 및 설치..."
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
bash miniconda.sh -b -p $INSTALL_DIR
rm miniconda.sh

echo "🔗 Conda 경로를 쉘 설정 파일에 등록..."
# 중복 방지를 위해 기존 라인 제거 후 추가
sed -i '/conda shell.bash hook/d' $SHELL_RC
echo "" >> $SHELL_RC
echo "# >>> conda initialize >>>" >> $SHELL_RC
echo "eval \"\$($INSTALL_DIR/bin/conda shell.bash hook)\"" >> $SHELL_RC
echo "# <<< conda initialize <<<" >> $SHELL_RC

# 현재 쉘에 즉시 적용
eval "$($INSTALL_DIR/bin/conda shell.bash hook)"

echo "🔄 Conda 업데이트..."
conda update -n base -c defaults conda -y

echo "🌱 가상환경 gpt2 생성 및 패키지 설치..."
conda create -n gpt2 python=3.10 -y
conda activate gpt2
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
pip install transformers tiktoken

echo "✅ 설치 확인:"
python -c "import torch, transformers, tiktoken; print('🎉 설치 완료!')"

echo "📌 다음 로그인부터는 conda 명령이 자동으로 인식됩니다. 터미널을 다시 시작하거나 'source ~/.bashrc'를 실행하세요."
