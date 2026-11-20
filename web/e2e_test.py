"""Tarayıcı demosunun uçtan uca testi (Chrome + Playwright, geliştirme sunucusuyla).

Önce:  python web/dev_server.py 8765
Sonra: python web/e2e_test.py
Ekran görüntüleri /tmp/shots altına yazılır. Pyodide'nin kendisini test etmez
(o kısım README_WEB.md'deki yayın sonrası deneme listesiyle kontrol edilir).
"""
import asyncio, os, sys
os.makedirs('/tmp/shots', exist_ok=True)
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = await b.new_page(viewport={"width":1440,"height":900}, accept_downloads=True)
        errs=[]
        pg.on("console", lambda m: errs.append(m.text) if m.type=="error" else None)
        pg.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto("http://127.0.0.1:8765/?dev=1")
        await pg.wait_for_function("window.__sfReady === true", timeout=15000)
        await pg.screenshot(path="/tmp/shots/1_giris.png")
        await pg.click("[data-act=demo]")
        await pg.wait_for_selector(".step")
        await pg.wait_for_timeout(500)
        await pg.screenshot(path="/tmp/shots/2_demo.png")
        print("notice:", (await pg.inner_text("#notice"))[:200])
        await pg.click("[data-x=fix]"); await pg.wait_for_timeout(600)
        print("after fix notice:", repr((await pg.inner_text("#notice"))[:100]))
        print("rows:", await pg.inner_text("#preview-count"))
        # vardiya verisi, step click
        await pg.click(".ds-list li:has-text('Vardiya verisi')"); await pg.wait_for_timeout(400)
        steps = await pg.locator(".step").all_inner_texts(); print(len(steps), [s.split('\n')[0][:50] for s in steps])
        await pg.locator(".step").nth(2).click(); await pg.wait_for_timeout(400)
        print("title:", await pg.inner_text("#preview-title"))
        await pg.screenshot(path="/tmp/shots/3_adim.png")
        # add calc with wrong column -> error in modal
        await pg.locator(".step").last.click(); await pg.wait_for_timeout(300)
        await pg.click("[data-act=add-menu]"); await pg.click("#add-menu button:has-text('Hesaplanan sütun')")
        await pg.fill("#f_name", "Puan"); await pg.fill("#f_formula", "[Toplanan] * 2")
        await pg.click("#modal-form button[type=submit]"); await pg.wait_for_timeout(400)
        print("modal err:", (await pg.inner_text("#modal-error"))[:160])
        await pg.screenshot(path="/tmp/shots/4_hata.png")
        await pg.fill("#f_formula", ""); await pg.click(".chip:has-text('Toplanan Adet')"); await pg.type("#f_formula", " * 2")
        await pg.click("#modal-form button[type=submit]"); await pg.wait_for_timeout(500)
        print("modal hidden:", await pg.is_hidden("#modal"))
        cols = await pg.locator("#grid th").all_inner_texts(); print("cols:", cols[-3:])
        # filter form
        await pg.click("[data-act=add-menu]"); await pg.click("#add-menu button:has-text('Filtre')")
        await pg.select_option("[data-cond=cond][data-part=column]", "Vardiya")
        await pg.fill("[data-cond=cond][data-part=value]", "Gece")
        await pg.click("#modal-form button[type=submit]"); await pg.wait_for_timeout(500)
        print("after filter:", await pg.inner_text("#preview-count"))
        # undo
        await pg.click("[data-act=undo]"); await pg.wait_for_timeout(400)
        print("after undo:", await pg.inner_text("#preview-count"))
        # toggle a step
        await pg.locator(".step").nth(1).hover(); await pg.locator(".step").nth(1).locator("[data-t=toggle]").click(); await pg.wait_for_timeout(400)
        print("toggled count:", await pg.inner_text("#preview-count"))
        await pg.locator(".step").nth(1).hover(); await pg.locator(".step").nth(1).locator("[data-t=toggle]").click(); await pg.wait_for_timeout(400)
        # next day
        await pg.click("[data-act=nextday]"); await pg.wait_for_timeout(600)
        print("day:", await pg.inner_text("#day-info"), await pg.inner_text("#preview-count"))
        # group form
        await pg.click("[data-act=add-menu]"); await pg.click("#add-menu button:has-text('Grupla')")
        await pg.check("[data-multi=by][value='Ekip']")
        await pg.select_option("#f_vcol", "Toplanan Adet")
        await pg.click("#modal-form button[type=submit]"); await pg.wait_for_timeout(500)
        print("group title:", await pg.inner_text("#steps-title"), (await pg.locator('#grid tbody tr').all_inner_texts())[:4])
        # lookup form on Vardiya: need fresh. validate stop
        await pg.click(".ds-list li:has-text('Vardiya verisi')"); await pg.wait_for_timeout(300)
        await pg.click("[data-act=add-menu]"); await pg.click("#add-menu button:has-text('Doğrula')")
        await pg.select_option("#f_check", "range"); await pg.select_option("#f_column", "Hatalı Adet"); await pg.fill("#f_max", "2"); await pg.select_option("#f_on_fail","stop")
        await pg.click("#modal-form button[type=submit]"); await pg.wait_for_timeout(500)
        await pg.click("[data-act=export]"); await pg.wait_for_timeout(600)
        print("export stop notice:", (await pg.inner_text("#notice"))[:200])
        await pg.screenshot(path="/tmp/shots/5_durdur.png")
        await pg.click("[data-act=undo]"); await pg.wait_for_timeout(400)
        async with pg.expect_download() as dl:
            await pg.click("[data-act=export]")
        d = await dl.value; await d.save_as("/tmp/shots/rapor.xlsx"); print("download:", d.suggested_filename)
        # upload csv
        open("/tmp/shots/test.csv","w",encoding="utf-8").write("Ürün;Adet;Depo\nKalem;10;İzmir\nDefter;5;İzmir \nSilgi;;Ankara\n")
        await pg.set_input_files("#file2", "/tmp/shots/test.csv"); await pg.wait_for_timeout(800)
        print("upload:", await pg.inner_text("#steps-title"), await pg.inner_text("#preview-count"))
        await pg.screenshot(path="/tmp/shots/6_yukle.png")
        await pg.set_viewport_size({"width":390,"height":844}); await pg.wait_for_timeout(300)
        await pg.screenshot(path="/tmp/shots/7_mobil.png", full_page=True)
        print("ERRORS:", errs)
        assert not errs, errs
        await b.close()
asyncio.run(main())
