#!/bin/bash

# 设置颜色输出
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO] $1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

# 检查命令执行状态
check_status() {
    if [ $? -eq 0 ]; then
        log_info "$1 成功"
    else
        log_error "$1 失败"
        exit 1
    fi
}

# 1. 初始化环境
init_environment() {
    log_info "开始安装基础环境..."
    sudo yum update -y
    sudo yum install -y python3 python3-pip git
    check_status "基础环境安装"
}

# 2. 创建目录并克隆代码
clone_repository() {
    log_info "创建目录并克隆代码..."
    
    # 创建目录
    sudo mkdir -p /data
    sudo chown -R $(whoami):$(whoami) /data
    cd /data
    
    # 检查目录是否已存在
    if [ -d "binance_python_connector" ]; then
        log_info "目录已存在，正在删除..."
        rm -rf binance_python_connector
    fi
    
    # 克隆代码
    git clone https://github.com/Robin3910/binance_python_connector.git
    check_status "代码克隆"
}

# 3&4. 切换目录和分支
switch_branch() {
    log_info "切换目录和分支..."
    cd /data/binance_python_connector
    git checkout -b feat_lele origin/feat_lele
    check_status "分支切换"
}

# 5. 安装Python依赖
install_requirements() {
    log_info "安装Python依赖..."
    pip3 install -r requirements.txt
    check_status "依赖安装"
}

# 6. 启动项目
start_project() {
    log_info "启动项目..."
    # 检查是否已有运行的进程
    if pgrep -f "python3 app.py" > /dev/null; then
        log_info "发现已运行的进程，正在停止..."
        pkill -f "python3 app.py"
        sleep 2
    fi
    
    nohup python3 app.py > app.log 2>&1 &
    check_status "项目启动"
    
    # 显示进程信息
    PID=$(pgrep -f "python3 app.py")
    if [ ! -z "$PID" ]; then
        log_info "项目已启动，进程ID: $PID"
        log_info "日志文件位置: /data/binance_python_connector/app.log"
    fi
}

# 主函数
main() {
    log_info "开始执行初始化脚本..."
    
    init_environment
    clone_repository
    switch_branch
    install_requirements
    start_project
    
    log_info "全部初始化完成！"
}

# 运行主函数
main