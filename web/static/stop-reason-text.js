// Câu cho từng MÃ DỪNG của một lượt tải (`jobs.ly_do_dung`) — dùng ở thẻ lượt tải
// (`app.js`) và ở trang Hướng dẫn (`huong-dan.html`, bảng "Vì sao lượt tải dừng").
//
// Tách khỏi `app.js` vì bảng ở đó nằm trong IIFE (`app.js:1`), nên trang nào không
// chạy `app.js` thì không đọc được — và trang Hướng dẫn không được chạy `app.js`
// (nó dựng cả trang tải). Một bảng, hai chỗ đọc: bản chép thứ hai là bản sẽ lệch.
//
// Thêm mã dừng ở server ⇒ thêm câu ở ĐÂY (test `test_moi_ma_dung_deu_co_cau_tren_giao_dien`).
const STOP_REASON_TEXT = {
    stalled: "Dừng sớm: nhiều trang liên tiếp không thấy video mới — có thể " +
             "nguồn này đã hết video TikTok đang cho xem, không phải lỗi.",
    page_cap: "Dừng sớm: đã quét hết số trang cho phép mà chưa đủ số lượng " +
               "yêu cầu — nguồn có thể còn video, thử chạy lại lượt tải này.",
    // Mã này phát cả khi lỗi ngay trang đầu (lượt 0 video ⇒ "Lỗi") lẫn giữa
    // chừng (đã có vài video ⇒ "Xong"/"Thiếu"), nên câu phải đúng cả hai ca.
    index_failed: "Không đọc tiếp được hashtag: nguồn liệt kê bên ngoài (không " +
                  "phải TikTok) bị lỗi — thử lại sau.",
    // Mã này phát cả khi trang hashtag KHÔNG TẢI ĐƯỢC (mạng, TikTok chặn/giới
    // hạn — `_fetch` trả None) lẫn khi tải được mà không có mã. Câu không được
    // khẳng định "hashtag sai" — lúc lỗi mạng hashtag hoàn toàn đúng.
    hashtag_khong_tra_duoc: "Không đọc được hashtag: không tra được mã của " +
                            "hashtag này trên TikTok — có thể TikTok/mạng đang " +
                            "không phản hồi, hoặc hashtag sai/không tồn tại. " +
                            "Kiểm lại hashtag; nếu đúng thì đợi một lúc rồi " +
                            "thử lại.",
    // Ba mã dưới đây sinh ra 21/09 cùng lúc với việc nhánh music/search/profile
    // biết đào sâu. Mỗi câu phải khuyên MỘT việc khác nhau — đó là cả lý do
    // chúng là ba mã chứ không phải một:
    //   · hết giờ / hết vòng ⇒ chạy lại CÓ THỂ ra thêm
    //   · nghi bị chặn       ⇒ NGHỈ đã, chạy lại ngay chỉ làm đậm dấu vết
    //   · đã có hết          ⇒ ĐỔI NGUỒN (mã `already_owned`, đã có ở trên)
    // Gộp chúng thành "không lấy đủ video" là quay về đúng sự im lặng mà bản
    // vá này sinh ra để chấm dứt.
    het_thoi_gian: "Dừng: hết thời gian cho một lượt tải (10 phút) trước khi " +
                   "đủ số bạn xin. Những video đã tìm được vẫn được giữ — " +
                   "chạy lại lượt này có thể ra thêm.",
    het_vong: "Dừng: đã quét lại hết số vòng cho phép mà chưa đủ số bạn xin. " +
              "Nguồn có thể còn video — chạy lại lượt này có thể ra thêm.",
    nghi_bi_chan: "Dừng: nguồn đang trả video rồi đột ngột ngừng — nhiều khả " +
                  "năng TikTok đang tạm chặn. Hãy NGHỈ một lúc rồi chạy lại; " +
                  "chạy lại ngay thường bị chặn tiếp.",
    // Bốn mã cookie: người dùng TỰ CHỮA ĐƯỢC cả bốn, nên câu chữ phải nói
    // cách chữa, không được rơi vào nhánh "báo cho người phát triển" ở dưới.
    // Nguồn còn sống, chỉ là thư viện đã có hết những gì nó đưa ra. Câu này
    // KHÔNG được bảo "thử chạy lại" — chạy lại cũng ra đúng như vậy, chỉ tốn
    // thêm lượt gọi TikTok.
    // Đĩa máy chạy dưới ngưỡng an toàn giữa job (Drive / Facebook Ads): job dừng TRƯỚC file kế. File đã
    // lên Drive vẫn còn; chạy lại sau khi đĩa có chỗ sẽ bỏ qua chúng và tải phần còn lại.
    het_dia: "Dừng: ổ đĩa của máy chạy sắp đầy nên job dừng trước khi tải tiếp. Những video đã lên " +
             "Drive vẫn còn — chạy lại sau khi đĩa có chỗ để tải phần còn lại.",
    // Trần IP của nền tảng link lẻ (YouTube, Instagram…): dùng chung cho cả văn phòng, nên job DỪNG chứ không
    // ngủ chờ — để các nền tảng khác phía sau không bị kẹt.
    tran_gio: "Dừng: nền tảng này đã chạm trần số lượt mỗi giờ của cả hệ thống (giữ cho IP văn phòng không bị " +
              "gắn cờ). Video đã tải vẫn còn — chạy lại sau chừng một giờ để tải phần còn lại.",
    tran_ngay: "Dừng: nền tảng này đã chạm trần số lượt trong NGÀY (giờ VN) của cả hệ thống. Video đã tải vẫn " +
               "còn — chạy lại vào ngày mai để tải phần còn lại.",
    bi_chan: "Dừng: nền tảng báo nghi ngờ truy cập tự động (bot-check / captcha / giới hạn tần suất). Nền tảng " +
             "này tạm tắt cho tới khi quản trị viên bật lại — đừng chạy lại ngay, việc đó chỉ làm đậm dấu vết.",
    thieu_deno: "Dừng: máy chạy chưa có Deno nên không tải được YouTube — đây là lỗi cấu hình máy, không phải " +
                "lỗi video. Báo người quản trị.",
    already_owned: "Xong: thư viện đã có hết video mà nguồn này đang đưa ra. " +
                   "Chạy lại cũng không ra thêm — thử hashtag hoặc nguồn khác.",
    // Lượt rỗng với mã này giờ ghi "Lỗi" (không còn "Xong"), nên câu không được
    // mở bằng "Xong:". Nhánh hashtag cũng phát mã này khi nguồn hết trang mà
    // chưa đủ số xin (`hashtag_enumerator.py`), nên câu phải đúng cả hai ca.
    source_empty: "Nguồn không đưa thêm video nào cho link này. Nếu chưa tải " +
                  "được video nào: link có thể sai hoặc đã hết hạn, hoặc nguồn " +
                  "chưa có video — kiểm lại link.",
    // KHÔNG phải "đã tải rồi": feed TikTok trả RỖNG (0 byte) ở mọi lần hỏi,
    // nên việc thư viện có hay không chưa từng được hỏi tới. Đo 01–02/10: trang
    // hiện captcha với trình duyệt tự động; không cookie / cookie khác rỗng y
    // hệt ⇒ KHÔNG được khuyên dán lại cookie (bản cũ khuyên vậy là chỉ sai hướng).
    // "Thường do" chứ không khẳng định: mã này dùng chung cho search/nhạc/trang
    // cá nhân, còn captcha mới thấy tận mắt ở trang cá nhân. Chỉ khuyên HASHTAG:
    // đường hashtag gọi API bằng urllib (`hashtag_enumerator`), không qua trình
    // duyệt; khuyên "nhạc/tìm kiếm" là khuyên đổi sang đúng loại trang vừa rỗng.
    feed_rong: "Dừng: TikTok trả kết quả RỖNG cho link này (không phải vì bạn " +
               "đã tải rồi). Thường do TikTok đang đòi xác minh (captcha) với " +
               "trình duyệt tự động — dán lại cookie không chữa được. Đợi một " +
               "lúc rồi thử lại, hoặc lấy video qua link hashtag.",
    cookie_khong_doc_duoc: "Dừng: tệp cookie của bạn không đọc được. Hãy xuất " +
                           "lại từ Cookie-Editor và chọn đúng định dạng JSON " +
                           "(không phải Header String hay Netscape), rồi dán lại.",
    cookie_rong: "Dừng: tệp cookie của bạn không có cookie nào. Hãy xuất lại " +
                 "khi đang mở tiktok.com và đã đăng nhập.",
    cookie_khong_phai_tiktok: "Dừng: cookie bạn đã dán không phải cookie TikTok " +
                              "(không có cookie nào của tiktok.com). Vào Cài đặt, " +
                              "dán lại cookie xuất khi đang mở tiktok.com.",
    cookie_chua_dang_nhap: "Dừng: cookie của bạn không có phiên đăng nhập — " +
                           "có vẻ được xuất lúc chưa đăng nhập TikTok. Đăng " +
                           "nhập tiktok.com rồi xuất lại cookie.",
    cookie_het_han: "Dừng: cookie đăng nhập của bạn đã hết hạn. Vào lại " +
                    "tiktok.com, xuất cookie mới rồi dán lại.",
    // Mã của luồng giải xác minh trong popup (`LD_*` ở web/giai_captcha.py; test
    // `test_moi_ma_dung_deu_co_cau_tren_giao_dien` gom cả chúng). Mỗi câu nói đúng NGUYÊN
    // NHÂN và việc người dùng làm được. Không câu nào được nói "đã bắt đầu tải": ở mọi
    // mã dưới đây job CHƯA tải video nào. Thẻ job ở `cho_xac_minh` với `feed_rong` /
    // `khong_do_duoc_feed` dùng câu riêng trỏ tới nút "Tôi giải ngay" (`giai-captcha-the-job.js`).
    khong_do_duoc_feed: "Dừng quét: không đo được danh sách video của trang này — " +
                        "nhiều khả năng TikTok đang đòi xác minh (captcha). Chưa tải " +
                        "video nào. Bấm “Tôi giải ngay” để giải trong cửa sổ Video " +
                        "Desk (tool không tự giải).",
    xac_minh_qua_han: "Đã kết thúc: lượt này chờ người giải xác minh quá 24 giờ mà " +
                      "chưa ai giải nên tool dừng. Chưa tải video nào. Tạo lượt tải " +
                      "mới nếu vẫn cần trang này.",
    feed_rong_khong_captcha: "Đã dừng theo yêu cầu: người giải bấm “Dừng job” vì không " +
                             "thấy xác minh nào để giải. Chưa tải video nào — TikTok " +
                             "vẫn trả kết quả rỗng cho trang này. Đợi một lúc rồi tạo " +
                             "lượt mới, hoặc lấy video qua link hashtag.",
    captcha_chua_xong: "Đã bấm “Đã giải xong” nhưng TikTok vẫn đòi xác minh nên tool " +
                       "dừng quét. Chưa tải video nào. Bấm “Tôi giải ngay” để thử lại " +
                       "nếu còn lượt.",
    khong_ai_xem: "Máy chủ đã mở lượt giải nhưng không có cửa sổ nào nhận quyền điều " +
                  "khiển kịp nên đã đóng trang. Chưa tải video nào. Bấm “Tôi giải " +
                  "ngay” rồi giữ cửa sổ giải mở.",
    het_gio_giai: "Hết 5 phút giải xác minh mà chưa bấm “Đã giải xong”; trang trên " +
                  "máy chủ đã đóng. Chưa tải video nào. Bấm “Tôi giải ngay” để thử " +
                  "lại nếu còn lượt.",
    loi_trinh_duyet: "Trình duyệt trên máy chủ gặp lỗi khi giải xác minh nên lượt giải " +
                     "đã đóng. Chưa tải video nào. Thử “Tôi giải ngay” lại; lặp lại " +
                     "nhiều lần thì báo người phát triển.",
    mo_trang_truot: "Máy chủ không mở được trang này kịp (mạng hoặc TikTok phản hồi " +
                    "chậm). Chưa tải video nào. Đợi một lúc rồi bấm “Tôi giải ngay” lại.",
    roi_mien: "Trang trên máy chủ bị chuyển sang một địa chỉ khác trang ban đầu nên " +
              "tool đóng lượt giải để an toàn. Chưa tải video nào. Thử “Tôi giải " +
              "ngay” lại.",
    khong_co_khung: "Máy chủ mở được trang nhưng không lấy được ảnh để bạn xem (quá " +
                    "20 giây). Chưa tải video nào. Thử “Tôi giải ngay” lại.",
    gesture_bo_do_qua_nhieu: "Thao tác kéo bị ngắt quá 2 lần trong một lượt giải nên " +
                             "lượt giải đã đóng. Chưa tải video nào. Bấm “Tôi giải ngay” " +
                             "và kéo một lần liền mạch, giữ chuột trong khung ảnh.",
    khoi_dong_lai: "Máy chủ khởi động lại giữa lượt giải xác minh nên lượt giải đã " +
                   "đóng. Chưa tải video nào. Bấm “Tôi giải ngay” để giải lại.",
    loi_he_thong: "Máy chủ gặp lỗi bất ngờ giữa lượt giải xác minh nên lượt giải đã " +
                  "đóng. Chưa tải video nào. Thử “Tôi giải ngay” lại; lặp lại thì báo " +
                  "người phát triển.",
    tinh_nang_giai_tat: "Job đã dừng vì tính năng giải xác minh đang tắt (máy chủ khởi " +
                        "động lại khi tính năng bị tắt). Chưa tải video nào. Tạo lượt " +
                        "tải mới khi tính năng được bật lại.",
  };
window.STOP_REASON_TEXT = Object.freeze(STOP_REASON_TEXT);
