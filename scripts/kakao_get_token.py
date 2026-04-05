import requests
import webbrowser

# ================= [수정된 설정 부분] =================
# 대표님의 카카오 디벨로퍼스 앱 정보를 직접 입력했습니다.
REST_API_KEY = 'f5e26baa639bdde5643c6f7664b24f01'
CLIENT_SECRET = 'lHxA3xPNN64yW5wncsdrKZzxoRjG9gFm'
REDIRECT_URI = 'http://localhost:3000'
# =====================================================

def get_tokens():
    print("🚀 [카카오 정식 액세스 토큰 발급 프로세스 시작]")
    
    # 1. 인가 코드 발급을 위한 브라우저 실행
    auth_url = f"https://kauth.kakao.com/oauth/authorize?client_id={REST_API_KEY}&redirect_uri={REDIRECT_URI}&response_type=code"
    print("\n[STEP 1] 브라우저가 열리면 카카오 로그인을 완료해 주세요.")
    webbrowser.open(auth_url)
    
    # 2. 사용자로부터 리다이렉트된 URL 전체 입력받기
    print("\n[STEP 2] 로그인이 끝나고 하얀 화면이 나오면, 주소창 전체를 복사해 아래에 붙여넣으세요.")
    full_url = input("👉 주소창 URL 전체 붙여넣기: ").strip()
    
    # URL에서 인가 코드(code)만 자동 추출
    try:
        if 'code=' in full_url:
            auth_code = full_url.split('code=')[1].split('&')[0]
        else:
            auth_code = full_url # 코드만 직접 넣었을 경우 대비
            
        print(f"\n✅ 인가 코드 추출 성공: {auth_code[:10]}...")
        
        # 3. 액세스 토큰 요청 (클라이언트 시크릿을 포함하여 서버 인증 통과)
        token_url = "https://kauth.kakao.com/oauth/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": REST_API_KEY,
            "client_secret": CLIENT_SECRET,  # 웹에서 설정한 비밀번호를 직접 전달합니다.
            "redirect_uri": REDIRECT_URI,
            "code": auth_code
        }
        
        print("\n[STEP 3] 카카오 서버에 정식 토큰을 요청하는 중입니다...")
        response = requests.post(token_url, data=payload)
        tokens = response.json()
        
        # 결과 출력
        if "access_token" in tokens:
            print("\n" + "="*60)
            print("🎉 [축하합니다! 발급 성공] 아래 토큰 정보를 사용하세요.")
            print(f"▶ Access Token (정식 코드): \n{tokens['access_token']}")
            print(f"\n▶ Refresh Token (갱신 코드): \n{tokens['refresh_token']}")
            print("="*60)
            print("\n💡 이제 위 Access Token을 복사하여 알림 전송 코드에 넣으시면 됩니다.")
        else:
            print(f"\n❌ [토큰 요청 실패]: {tokens}")
            print("⚠️ 카카오 로그인 설정에서 '클라이언트 시크릿' 값이 일치하는지 확인해 주세요.")
            
    except Exception as e:
        print(f"\n❌ [오류 발생]: {e}")

if __name__ == "__main__":
    get_tokens()
