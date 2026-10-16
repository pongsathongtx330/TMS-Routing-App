import streamlit as st
import pandas as pd
import numpy as np
import io
import folium
import streamlit.components.v1 as components

# ---------------------------------------------------------
# การตั้งค่าหน้าเว็บ Streamlit
# ---------------------------------------------------------
st.set_page_config(page_title="TMS Route Optimization", layout="wide")
st.title("🚛 ระบบบริหารจัดการเส้นทางและลดต้นทุนขนส่ง (TMS)")
st.markdown("แสดงผลลัพธ์การจัดเส้นทางที่ลดต้นทุนและระยะทางได้อย่างแม่นยำ (อ้างอิงข้อมูลจากไฟล์แบบ 100%)")

# ---------------------------------------------------------
# แถบด้านข้าง (Sidebar) สำหรับตั้งค่าพารามิเตอร์
# ---------------------------------------------------------
st.sidebar.header("⚙️ ตั้งค่าพารามิเตอร์")
# ตั้งค่าเริ่มต้นให้ตรงกับไฟล์แรก (เส้นทางการขนส่ง.xlsx) ที่ยังไม่จัด
original_cost = st.sidebar.number_input("ต้นทุนเดิม (ก่อนจัดเส้นทาง)", value=36565.93) 

uploaded_file = st.sidebar.file_uploader("📂 อัปโหลดไฟล์ Excel (TMS_Savings_Route_Plan 2_2)", type=['xlsx'])

if uploaded_file is not None:
    try:
        # ---------------------------------------------------------
        # 1. อ่านข้อมูลพิกัดและ Demand
        # ---------------------------------------------------------
        df_dist = pd.read_excel(uploaded_file, sheet_name='1.Distance Matrix')
        df_coords = df_dist.iloc[2:, 0:3].reset_index(drop=True)
        df_coords.columns = ['ชื่อลูกค้า', 'Latitude', 'Longitude']
        
        # แปลงเป็นตัวเลข
        df_coords['Latitude'] = pd.to_numeric(df_coords['Latitude'], errors='coerce')
        df_coords['Longitude'] = pd.to_numeric(df_coords['Longitude'], errors='coerce')
        
        depot_row = df_coords[df_coords['ชื่อลูกค้า'] == 'โรงงาน (จุดเริ่มต้น)']
        depot_lat = depot_row['Latitude'].values[0] if not depot_row.empty else 13.52596
        depot_lon = depot_row['Longitude'].values[0] if not depot_row.empty else 100.173329

        df_demand = pd.read_excel(uploaded_file, sheet_name='Demand Mapping')
        df_demand = df_demand[['ชื่อร้าน/Node', 'Demand (กก.)']]
        df_coords = df_coords.merge(df_demand, left_on='ชื่อลูกค้า', right_on='ชื่อร้าน/Node', how='left')
        df_coords['Demand (กก.)'] = df_coords['Demand (กก.)'].fillna(0)

        # ---------------------------------------------------------
        # 2. อ่านข้อมูลสรุปเส้นทาง (Route Summary) เพื่อให้ต้นทุนเป๊ะ
        # ---------------------------------------------------------
        df_summary = pd.read_excel(uploaded_file, sheet_name='Route Summary')
        # กรองเอาเฉพาะบรรทัดที่มีเส้นทางรถ
        df_routes = df_summary.dropna(subset=['ลำดับเส้นทาง']).copy()
        
        # ดึงต้นทุนรวมและระยะทางรวมจากบรรทัด "รวม" (แถวสุดท้าย)
        total_row = df_summary[df_summary['รถ'] == 'รวม']
        optimized_cost = total_row['ต้นทุนโดยประมาณ (บาท)'].values[0]
        total_distance = total_row['ระยะทางรวมโดยประมาณ (กม.)'].values[0]
        
        cost_saving = original_cost - optimized_cost

        # ---------------------------------------------------------
        # 3. อ่านตาราง Savings Algorithm 
        # ---------------------------------------------------------
        # ข้ามบรรทัดที่เป็นคำอธิบาย เพื่อให้หัวตารางดึงมาได้ถูกต้อง (header=3)
        df_savings = pd.read_excel(uploaded_file, sheet_name='Savings Algorithm', header=3)

        # ================= Dashboard =================
        st.subheader("📊 เปรียบเทียบผลลัพธ์การลดต้นทุน")
        col1, col2, col3 = st.columns(3)
        col1.metric("ต้นทุนเดิม (ก่อนจัดเส้นทาง)", f"{original_cost:,.2f} ฿")
        col2.metric("ต้นทุนใหม่ (ตามไฟล์ Excel)", f"{optimized_cost:,.2f} ฿", delta=f"-{cost_saving:,.2f} ฿")
        col3.metric("ระยะทางรวมใหม่", f"{total_distance:,.2f} กม.")
        
        # ================= แผนที่ =================
        st.subheader("🗺️ แผนที่เส้นทางการจัดส่ง")
        map_colors = ['blue', 'green', 'purple', 'orange', 'darkred', 'lightred', 
                      'beige', 'darkblue', 'darkgreen', 'cadetblue', 'darkpurple', 'pink']
        
        m = folium.Map(location=[depot_lat, depot_lon], zoom_start=6)
        
        folium.Marker(
            [depot_lat, depot_lon],
            popup="<b>โรงงาน</b>",
            icon=folium.Icon(color="red", icon="home", prefix='fa')
        ).add_to(m)
        
        # วาดเส้นทางตามที่จัดไว้ในไฟล์
        for idx, row in df_routes.iterrows():
            color = map_colors[idx % len(map_colors)]
            route_str = row['ลำดับเส้นทาง']
            
            # แยกชื่อร้านออกจากข้อความเส้นทาง
            nodes = [n.strip() for n in route_str.split('→') if n.strip()]
            
            route_coords = []
            for node in nodes:
                search_node = 'โรงงาน (จุดเริ่มต้น)' if node == 'โรงงาน' else node
                node_data = df_coords[df_coords['ชื่อลูกค้า'] == search_node]
                
                if not node_data.empty:
                    lat = node_data['Latitude'].values[0]
                    lon = node_data['Longitude'].values[0]
                    demand = node_data['Demand (กก.)'].values[0]
                    
                    if not pd.isna(lat) and not pd.isna(lon):
                        route_coords.append([lat, lon])
                        if search_node != 'โรงงาน (จุดเริ่มต้น)':
                            folium.Marker(
                                [lat, lon],
                                popup=f"<b>{search_node}</b><br>Demand: {demand} กก.",
                                icon=folium.Icon(color=color, icon="info-sign")
                            ).add_to(m)
                            
            if len(route_coords) > 1:
                folium.PolyLine(route_coords, color=color, weight=3, opacity=0.8).add_to(m)
            
        map_html = m._repr_html_()
        components.html(map_html, height=600, width=1200)

        # ================= ตารางสรุป =================
        st.subheader("📍 สรุปเส้นทางเดินรถ (Optimized Routes)")
        st.dataframe(df_routes, use_container_width=True)

        st.subheader("🧮 ตาราง Savings Matrix")
        st.dataframe(df_savings, use_container_width=True)

    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการโหลดไฟล์: {e}")
else:
    st.info("กรุณาอัปโหลดไฟล์ Excel (TMS_Savings_Route_Plan) ของคุณที่แถบด้านซ้ายมือเพื่อเริ่มการแสดงผล")
