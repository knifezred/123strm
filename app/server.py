from fastapi import FastAPI
from fastapi.responses import FileResponse
import uvicorn

app = FastAPI()

if __name__ == "__main__":
    """
    启动FastAPI应用
    默认监听127.0.0.1:8000
    """
    uvicorn.run(app, host="0.0.0.0", port=8000)

@app.get("/")
async def root():
    return {"message": "Hello World"}
# 创建一个获取文件下载链接的接口
@app.get("/download/{file_name}")
async def download_file(file_name: str):
    file_path = os.path.join(os.getcwd(), file_name)
    if os.path.isfile(file_path):
        return FileResponse(file_path, filename=file_name)
    else:
        return {"message": "文件未找到"}
